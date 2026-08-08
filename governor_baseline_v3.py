import redis, json, time, os
from collections import defaultdict, Counter

r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)

# ── Determine post-restart window from llm_audit ──
# The restart was at tick 1783297410 (2026-07-06T00:23:30Z)
# We'll use 1783297600 as the post-restart baseline
POST_RESTART_TS = 1783297600

print('=' * 70)
print('GOVERNOR BASELINE V3 — WITH LIVE MEMORY')
print('=' * 70)

# ── A. LLM calls from llm_audit (24h window) ──
print('\n[A] 24h LLM calls by char_id/source/system_path/success/provider/model')
print('-' * 70)

now = int(time.time())
window_24h = now - 86400

audit_entries = r.zrangebyscore('llm_audit', window_24h, now)
print(f'Total 24h llm_audit entries: {len(audit_entries)}')

llm_by_char = defaultdict(lambda: {'total': 0, 'success': 0, 'fail': 0, 'sources': Counter(), 'providers': Counter(), 'models': Counter(), 'system_paths': Counter()})
llm_by_source = Counter()
llm_by_provider = Counter()
llm_by_system_path = Counter()
llm_success_total = 0
llm_fail_total = 0
post_restart_entries = 0

for entry in audit_entries:
    try:
        data = json.loads(entry)
    except:
        continue
    ts = data.get('ts', 0)
    if ts >= POST_RESTART_TS:
        post_restart_entries += 1
    char_id = data.get('char_id', '')
    source = data.get('source', 'unknown')
    system_path = data.get('system_path', 'unknown')
    provider = data.get('provider', '')
    model = data.get('model', '')
    success = data.get('success', False)
    
    llm_by_char[char_id]['total'] += 1
    if success:
        llm_by_char[char_id]['success'] += 1
        llm_success_total += 1
    else:
        llm_by_char[char_id]['fail'] += 1
        llm_fail_total += 1
    llm_by_char[char_id]['sources'][source] += 1
    llm_by_char[char_id]['providers'][provider] += 1
    llm_by_char[char_id]['models'][model] += 1
    llm_by_char[char_id]['system_paths'][system_path] += 1
    llm_by_source[source] += 1
    llm_by_provider[provider] += 1
    llm_by_system_path[system_path] += 1

print(f'Post-restart entries: {post_restart_entries}')
print(f'24h success: {llm_success_total}, fail: {llm_fail_total}')
print(f'\n24h by source: {dict(llm_by_source)}')
print(f'24h by provider: {dict(llm_by_provider)}')
print(f'24h by system_path:')
for sp, c in llm_by_system_path.most_common(10):
    print(f'  {sp}: {c}')

print(f'\n24h LLM calls by char_id (top 20):')
for char_id, stats in sorted(llm_by_char.items(), key=lambda x: -x[1]['total'])[:20]:
    sources_str = ', '.join(f'{s}:{c}' for s, c in stats['sources'].most_common(3))
    print(f'  {char_id or "(blank)"}: total={stats["total"]} succ={stats["success"]} fail={stats["fail"]} sources=[{sources_str}]')

# ── B. Visible activity from npc_action_logs (24h) ──
# We need to query PostgreSQL for this
print('\n[B] 24h visible activity by char_id from npc_action_logs')
print('-' * 70)

try:
    import psycopg2
    db_url = os.environ.get('DATABASE_URL', 'postgresql://federation:federation@postgres:5432/federation')
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # Get visible action counts by char_id in last 24h
    cur.execute("""
        SELECT char_id, COUNT(*) as cnt
        FROM npc_action_logs
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        GROUP BY char_id
        ORDER BY cnt DESC
    """)
    visible_by_char = {}
    for row in cur.fetchall():
        visible_by_char[row[0] or '(blank)'] = row[1]
    
    print(f'24h visible activity (npc_action_logs) — {len(visible_by_char)} NPCs:')
    for char_id, count in sorted(visible_by_char.items(), key=lambda x: -x[1])[:20]:
        print(f'  {char_id}: {count} actions')
    
    # Total visible
    cur.execute("""
        SELECT COUNT(*) FROM npc_action_logs
        WHERE created_at >= NOW() - INTERVAL '24 hours'
    """)
    total_visible = cur.fetchone()[0]
    print(f'\nTotal 24h visible actions: {total_visible}')
    
    cur.close()
    conn.close()
except Exception as e:
    print(f'[B] PostgreSQL query failed: {e}')
    visible_by_char = {}
    total_visible = 0

# ── C. Redis memory state ──
print('\n[C] Redis memory state')
print('-' * 70)

mem_keys = list(r.scan_iter('npc_memory:*'))
summ_keys = list(r.scan_iter('npc_memory_summary:*'))
print(f'npc_memory:* key count: {len(mem_keys)}')
print(f'npc_memory_summary:* key count: {len(summ_keys)}')

# zcard per key
key_zcards = {}
all_events = []
categories = Counter()
score_dist = Counter()

for k in mem_keys:
    zc = r.zcard(k)
    key_zcards[k] = zc
    members = r.zrange(k, 0, -1)
    for m in members:
        try:
            data = json.loads(m)
            all_events.append((k, data))
            cat = data.get('category', data.get('type', 'unknown'))
            categories[cat] += 1
            score = data.get('memory_score', '?')
            score_dist[score] += 1
        except:
            pass

print(f'\nTop npc_memory:* keys by zcard:')
for k, zc in sorted(key_zcards.items(), key=lambda x: -x[1])[:20]:
    char_id = k.replace('npc_memory:', '')
    print(f'  {k}: {zc}')

print(f'\nCategory counts:')
for cat, c in categories.most_common():
    print(f'  {cat}: {c}')

print(f'\nScore distribution:')
for s, c in sorted(score_dist.items()):
    print(f'  score={s}: {c}')

# ── D. NPCs with high visible activity but low memory ──
print('\n[D] NPCs with high visible activity but low memory')
print('-' * 70)

mem_char_ids = {k.replace('npc_memory:', '') for k in mem_keys}
high_visible_low_mem = []
for char_id, vis_count in sorted(visible_by_char.items(), key=lambda x: -x[1]):
    if char_id == '(blank)':
        continue
    mem_key = f'npc_memory:{char_id}'
    mem_count = key_zcards.get(mem_key, 0)
    if mem_count == 0 and vis_count > 10:
        high_visible_low_mem.append((char_id, vis_count, mem_count))

if high_visible_low_mem:
    for char_id, vis, mem in high_visible_low_mem[:15]:
        print(f'  {char_id}: visible={vis}, memory={mem}')
else:
    print('  (none found)')

# ── E. NPCs with high memory but low visible activity ──
print('\n[E] NPCs with high memory but low visible activity')
print('-' * 70)

high_mem_low_visible = []
for k, zc in key_zcards.items():
    char_id = k.replace('npc_memory:', '')
    vis_count = visible_by_char.get(char_id, 0)
    if zc >= 3 and vis_count < 5:
        high_mem_low_visible.append((char_id, vis_count, zc))

if high_mem_low_visible:
    for char_id, vis, mem in high_mem_low_visible[:15]:
        print(f'  {char_id}: visible={vis}, memory={mem}')
else:
    print('  (none found)')

# ── F. NPCs with high LLM calls but low memory/visible payoff ──
print('\n[F] NPCs with high LLM calls but low memory/visible payoff')
print('-' * 70)

high_llm_low_payoff = []
for char_id, stats in llm_by_char.items():
    if not char_id or char_id == '(blank)':
        continue
    llm_total = stats['total']
    vis_count = visible_by_char.get(char_id, 0)
    mem_key = f'npc_memory:{char_id}'
    mem_count = key_zcards.get(mem_key, 0)
    if llm_total >= 5 and mem_count == 0 and vis_count < 5:
        high_llm_low_payoff.append((char_id, llm_total, vis_count, mem_count, stats['fail']))

if high_llm_low_payoff:
    for char_id, llm, vis, mem, fails in high_llm_low_payoff[:15]:
        print(f'  {char_id}: llm={llm} ({fails} fail), visible={vis}, memory={mem}')
else:
    print('  (none found)')

# ── G. NPCs with summaries present ──
print('\n[G] NPCs with summaries present')
print('-' * 70)

summ_char_ids = {k.replace('npc_memory_summary:', '') for k in summ_keys}
print(f'NPCs with summaries: {len(summ_char_ids)}')
for sid in sorted(summ_char_ids)[:20]:
    mem_key = f'npc_memory:{sid}'
    zc = key_zcards.get(mem_key, 0)
    llm_count = llm_by_char.get(sid, {}).get('total', 0)
    print(f'  {sid}: memory_events={zc}, llm_calls_24h={llm_count}')

# ── Summary table: LLM + visible + memory per NPC ──
print('\n[FULL] Combined per-NPC summary (LLM / visible / memory)')
print('-' * 70)

all_char_ids = set(mem_char_ids) | set(visible_by_char.keys()) | set(llm_by_char.keys()) - {'(blank)'}
combined = []
for cid in all_char_ids:
    if not cid or cid == '(blank)':
        continue
    llm_total = llm_by_char.get(cid, {}).get('total', 0)
    llm_fail = llm_by_char.get(cid, {}).get('fail', 0)
    vis = visible_by_char.get(cid, 0)
    mem = key_zcards.get(f'npc_memory:{cid}', 0)
    combined.append((cid, llm_total, llm_fail, vis, mem))

# Sort by visible desc (most active first)
print(f'{"char_id":<15} {"llm_24h":>8} {"llm_fail":>9} {"visible":>8} {"memory":>8}')
print('-' * 55)
for cid, llm, fails, vis, mem in sorted(combined, key=lambda x: -x[3])[:30]:
    print(f'{cid:<15} {llm:>8} {fails:>9} {vis:>8} {mem:>8}')

print(f'\n... {len(combined)} total NPCs/entities')

# ── Tiering candidates ──
print('\n[TIERING] Provisional governor tier candidates')
print('-' * 70)

# High tier: LLM > 5 AND memory > 0 AND visible > 10
# Medium tier: some activity but not high
# Low tier: no LLM, low visible, no memory
high_tier = []
medium_tier = []
low_tier = []

for cid, llm, fails, vis, mem in combined:
    if llm >= 5 and mem > 0 and vis > 10:
        high_tier.append((cid, llm, vis, mem))
    elif llm > 0 or mem > 0 or vis > 5:
        medium_tier.append((cid, llm, vis, mem))
    else:
        low_tier.append((cid, llm, vis, mem))

print(f'High tier (llm>=5, mem>0, vis>10): {len(high_tier)}')
for cid, llm, vis, mem in high_tier[:10]:
    print(f'  {cid}: llm={llm}, vis={vis}, mem={mem}')

print(f'\nMedium tier (some activity): {len(medium_tier)}')
for cid, llm, vis, mem in medium_tier[:15]:
    print(f'  {cid}: llm={llm}, vis={vis}, mem={mem}')

print(f'\nLow tier (no activity): {len(low_tier)}')
for cid, llm, vis, mem in low_tier[:10]:
    print(f'  {cid}: llm={llm}, vis={vis}, mem={mem}')

# ── H. Errors check ──
print('\n[H] Error check (from logs - manual inspection needed)')
print('-' * 70)
print('Check backend/worker logs for memory/harvest errors manually.')
print(f'Current sim_last_tick: {r.get("sim_last_tick")}')

print('\n' + '=' * 70)
print('BASELINE V3 COMPLETE')
print('=' * 70)
