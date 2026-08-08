import redis, json, time, os, sys
from collections import defaultdict

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

started_at_ts = float(sys.argv[1]) if len(sys.argv) > 1 else 0

# --- Redis ---
r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)

audit = r.zrange('llm_audit', 0, 500)
post = [json.loads(a) for a in audit if json.loads(a).get('ts', 0) > started_at_ts]

print('POST_RESTART_ROWS:', len(post))

# Group by dimensions
by_char = defaultdict(int)
by_source = defaultdict(int)
by_path = defaultdict(int)
by_provider_model = defaultdict(int)
by_success = defaultdict(int)
latencies = defaultdict(list)
blank_by_source = defaultdict(int)

for d in post:
    cid = d.get('char_id', '')
    src = d.get('source', '')
    path = d.get('system_path', '')
    prov = d.get('provider', '')
    model = d.get('model', '')
    success = d.get('success', False)
    lat = d.get('latency_ms')
    by_char[cid] += 1
    by_source[src] += 1
    by_path[path] += 1
    by_provider_model[(prov, model)] += 1
    by_success[success] += 1
    if lat is not None:
        latencies[(prov, model)].append(lat)
    if not cid:
        blank_by_source[src] += 1

print('\n--- top NPCs by LLM calls (post-restart) ---')
for cid, count in sorted(by_char.items(), key=lambda x: -x[1])[:15]:
    print(f'  {cid}: {count}')

print('\n--- source counts ---')
for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
    print(f'  {src}: {count}')

print('\n--- system_path counts ---')
for path, count in sorted(by_path.items(), key=lambda x: -x[1]):
    print(f'  {path}: {count}')

print('\n--- provider/model counts ---')
for (prov, model), count in sorted(by_provider_model.items(), key=lambda x: -x[1])[:10]:
    avg_lat = round(sum(latencies[(prov, model)]) / len(latencies[(prov, model)]), 1) if latencies[(prov, model)] else 0
    print(f'  {prov} / {model}: {count} calls, avg latency {avg_lat}ms')

print('\n--- success/failure ---')
for succ, count in sorted(by_success.items(), key=lambda x: -x[1]):
    print(f'  {succ}: {count}')

print('\n--- blank char_id by source ---')
for src, count in sorted(blank_by_source.items(), key=lambda x: -x[1]):
    print(f'  {src}: {count}')

# --- Redis key sizes / TTLs ---
patterns = [
    'npc_thoughts:*',
    'npc_actions:*',
    'npc_decisions:*',
    'npc_activity:*',
    'npc_memory:*',
    'npc_memory_summary:*',
]
print('\n--- Redis key counts by pattern ---')
for pat in patterns:
    count = 0
    total_size = 0
    ttl_samples = []
    for key in r.scan_iter(pat):
        count += 1
        try:
            total_size += len(r.dump(key) or b'')
            ttl = r.ttl(key)
            if ttl is not None and ttl >= 0:
                ttl_samples.append(ttl)
        except Exception:
            pass
    avg_ttl = round(sum(ttl_samples) / len(ttl_samples), 0) if ttl_samples else -1
    print(f'  {pat}: {count} keys, avg_ttl={avg_ttl}s')

# --- Postgres npc_action_logs ---
if HAS_PSYCOPG2:
    try:
        db_url = os.environ.get('DATABASE_URL', '')
        if not db_url:
            print('\nPostgres: DATABASE_URL not set, skipping')
        else:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT char_id, entry_type, COUNT(*) as cnt, MAX(timestamp) as max_ts FROM npc_action_logs GROUP BY char_id, entry_type ORDER BY char_id, entry_type")
            rows = cur.fetchall()
            print('\n--- Postgres npc_action_logs counts ---')
            for row in rows:
                print(f'  {row["char_id"]} / {row["entry_type"]}: {row["cnt"]} (max_ts={row["max_ts"]})')
            cur.close()
            conn.close()
    except Exception as e:
        print(f'\nPostgres query failed: {e}')
else:
    print('\nPostgres: psycopg2 not installed, skipping')

# --- Visible NPCs from spectator ---
print('\n--- spectator visible NPCs (from recent npc_action_logs) ---')
if HAS_PSYCOPG2:
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT char_id, COUNT(*) as cnt, MAX(timestamp) as max_ts FROM npc_action_logs WHERE entry_type IN ('interaction', 'decision', 'cognition') GROUP BY char_id ORDER BY cnt DESC LIMIT 15")
        rows = cur.fetchall()
        for row in rows:
            print(f'  {row["char_id"]}: {row["cnt"]} visible entries, max_ts={row["max_ts"]}')
        cur.close()
        conn.close()
    except Exception as e:
        print(f'  Postgres visible query failed: {e}')
else:
    print('  psycopg2 not installed')
