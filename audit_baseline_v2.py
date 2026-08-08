import redis, json, time, os, sys, datetime
from collections import defaultdict

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# --- timestamps ---
now_ts = int(sys.argv[1]) if len(sys.argv) > 1 else int(time.time())
started_at_ts = float(sys.argv[2]) if len(sys.argv) > 2 else 0
window_24h = now_ts - 86400

print(f'now_ts={now_ts} ({datetime.datetime.utcfromtimestamp(now_ts).isoformat()}Z)')
print(f'started_at_ts={started_at_ts} ({datetime.datetime.utcfromtimestamp(started_at_ts).isoformat()}Z)')
print(f'window_24h={window_24h} ({datetime.datetime.utcfromtimestamp(window_24h).isoformat()}Z)')

# --- Redis ---
r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)

audit = r.zrange('llm_audit', 0, 500)
post_restart = [json.loads(a) for a in audit if json.loads(a).get('ts', 0) > started_at_ts]
last_24h = [json.loads(a) for a in audit if json.loads(a).get('ts', 0) > window_24h]

print('\n=== A. Post-restart LLM calls ===')
print(f'POST_RESTART_ROWS: {len(post_restart)}')
print(f'LAST_24H_ROWS: {len(last_24h)}')

# Group by dimensions
by_char = defaultdict(int)
by_source = defaultdict(int)
by_path = defaultdict(int)
by_provider_model = defaultdict(int)
by_success = defaultdict(int)
latencies = defaultdict(list)
blank_by_source = defaultdict(int)

for d in post_restart:
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
for cid, count in sorted(by_char.items(), key=lambda x: -x[1])[:20]:
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

# --- 24h LLM calls ---
print('\n=== A2. Last-24h LLM calls ===')
by_char_24h = defaultdict(int)
by_source_24h = defaultdict(int)
for d in last_24h:
    cid = d.get('char_id', '')
    src = d.get('source', '')
    by_char_24h[cid] += 1
    by_source_24h[src] += 1

print('\n--- top NPCs by LLM calls (24h) ---')
for cid, count in sorted(by_char_24h.items(), key=lambda x: -x[1])[:20]:
    print(f'  {cid}: {count}')

print('\n--- source counts (24h) ---')
for src, count in sorted(by_source_24h.items(), key=lambda x: -x[1]):
    print(f'  {src}: {count}')

# --- Postgres npc_action_logs ---
print('\n=== B. 24h npc_action_logs by char_id and entry_type ===')
print(f'window_24h={window_24h}')
if HAS_PSYCOPG2:
    try:
        db_url = os.environ.get('DATABASE_URL', '')
        if not db_url:
            print('DATABASE_URL not set')
        else:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT char_id, entry_type, COUNT(*) as cnt FROM npc_action_logs WHERE timestamp > %s GROUP BY char_id, entry_type ORDER BY char_id, entry_type", (window_24h,))
            rows = cur.fetchall()
            for row in rows:
                print(f'  {row["char_id"]} / {row["entry_type"]}: {row["cnt"]}')
            cur.close()
            conn.close()
    except Exception as e:
        print(f'Postgres query failed: {e}')
else:
    print('psycopg2 not installed')

# --- 24h visible interaction count by char_id ---
print('\n=== C. 24h visible interaction count by char_id ===')
if HAS_PSYCOPG2:
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT char_id, COUNT(*) as cnt FROM npc_action_logs WHERE timestamp > %s AND entry_type IN ('interaction', 'decision', 'cognition') GROUP BY char_id ORDER BY cnt DESC", (window_24h,))
        rows = cur.fetchall()
        for row in rows:
            print(f'  {row["char_id"]}: {row["cnt"]}')
        cur.close()
        conn.close()
    except Exception as e:
        print(f'Postgres visible query failed: {e}')
else:
    print('psycopg2 not installed')

# --- 24h Redis key counts and max zcard ---
print('\n=== D. 24h Redis key counts and max zcard by pattern ===')
patterns = [
    'npc_thoughts:*',
    'npc_actions:*',
    'npc_decisions:*',
    'npc_activity:*',
    'npc_memory:*',
    'npc_memory_summary:*',
]
for pat in patterns:
    count = 0
    total_size = 0
    ttl_samples = []
    max_zcard = 0
    for key in r.scan_iter(pat):
        count += 1
        try:
            total_size += len(r.dump(key) or b'')
            ttl = r.ttl(key)
            if ttl is not None and ttl >= 0:
                ttl_samples.append(ttl)
            if pat in ('npc_thoughts:*', 'npc_actions:*', 'npc_decisions:*', 'npc_activity:*', 'npc_memory:*', 'npc_memory_summary:*'):
                zc = r.zcard(key)
                if zc > max_zcard:
                    max_zcard = zc
        except Exception:
            pass
    avg_ttl = round(sum(ttl_samples) / len(ttl_samples), 0) if ttl_samples else -1
    print(f'  {pat}: {count} keys, max_zcard={max_zcard}, avg_ttl={avg_ttl}s')

# --- E. NPCs with LLM calls but zero 24h visible output ---
print('\n=== E. NPCs with LLM calls but zero 24h visible output ===')
llm_chars = set(by_char_24h.keys())
visible_chars = set()
if HAS_PSYCOPG2:
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT char_id FROM npc_action_logs WHERE timestamp > %s AND entry_type IN ('interaction', 'decision', 'cognition') GROUP BY char_id", (window_24h,))
        rows = cur.fetchall()
        visible_chars = {row['char_id'] for row in rows}
        cur.close()
        conn.close()
    except Exception as e:
        print(f'Postgres visible query failed: {e}')

no_visible = llm_chars - visible_chars
if no_visible:
    for cid in sorted(no_visible):
        print(f'  {cid}: {by_char_24h[cid]} LLM calls, 0 visible output')
else:
    print('  (none)')

# --- F. NPCs with high visible output but low/no LLM calls ---
print('\n=== F. NPCs with high visible output but low/no LLM calls ===')
if HAS_PSYCOPG2:
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT char_id, COUNT(*) as cnt 
            FROM npc_action_logs 
            WHERE timestamp > %s AND entry_type IN ('interaction', 'decision', 'cognition') 
            GROUP BY char_id 
            HAVING COUNT(*) > 10
            ORDER BY cnt DESC
        """, (window_24h,))
        rows = cur.fetchall()
        for row in rows:
            cid = row['char_id']
            cnt = row['cnt']
            llm_count = by_char_24h.get(cid, 0)
            if llm_count == 0:
                print(f'  {cid}: {cnt} visible, 0 LLM calls')
            elif llm_count < 3:
                print(f'  {cid}: {cnt} visible, {llm_count} LLM calls (low)')
        cur.close()
        conn.close()
    except Exception as e:
        print(f'Postgres high-visible query failed: {e}')
else:
    print('psycopg2 not installed')

# --- G. Memory system status ---
print('\n=== G. Memory system status ===')
mem_keys = list(r.scan_iter('npc_memory:*'))
mem_summary_keys = list(r.scan_iter('npc_memory_summary:*'))
print(f'npc_memory:* keys: {len(mem_keys)}')
print(f'npc_memory_summary:* keys: {len(mem_summary_keys)}')
if mem_keys:
    for k in mem_keys[:3]:
        val = r.get(k)
        print(f'  sample {k}: {val[:100] if val else None}...')
if mem_summary_keys:
    for k in mem_summary_keys[:3]:
        val = r.get(k)
        print(f'  sample {k}: {val[:100] if val else None}...')

# Check if memory is referenced in code
print('\n--- memory system code references ---')
import subprocess
result = subprocess.run(['grep', '-r', 'npc_memory', '/docker/federation-game/backend/'], capture_output=True, text=True)
if result.stdout:
    for line in result.stdout.split('\n')[:10]:
        print(f'  {line}')
