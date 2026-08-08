import redis, json, time

r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)

# Baseline
last_tick = r.get('sim_last_tick')
mem_before = list(r.scan_iter('npc_memory:*'))
summ_before = list(r.scan_iter('npc_memory_summary:*'))
print(f'BASELINE sim_last_tick: {last_tick}')
print(f'BASELINE npc_memory keys: {len(mem_before)}')
print(f'BASELINE npc_memory_summary keys: {len(summ_before)}')

# Wait for new tick (up to 12 min)
print('\nWaiting for new tick...')
for i in range(72):
    time.sleep(10)
    new_tick = r.get('sim_last_tick')
    if new_tick != last_tick:
        print(f'New tick detected: {new_tick}')
        break
else:
    print('No new tick after 720s')

# Post-tick counts
mem_after = list(r.scan_iter('npc_memory:*'))
summ_after = list(r.scan_iter('npc_memory_summary:*'))
print(f'\nPOST-TICK npc_memory keys: {len(mem_after)}')
print(f'POST-TICK npc_memory_summary keys: {len(summ_after)}')

# Top keys by zcard
print('\nTop npc_memory keys by zcard:')
key_counts = [(k, r.zcard(k)) for k in mem_after]
key_counts.sort(key=lambda x: -x[1])
for k, count in key_counts[:15]:
    print(f'  {k}: {count}')

# Sample 10 newest events across different NPCs
print('\nSample 10 newest events:')
sampled = 0
for k, count in key_counts:
    if sampled >= 10:
        break
    members = r.zrevrange(k, 0, 0)
    if members:
        data = json.loads(members[0])
        print(f'  {k}: type={data.get("type")} category={data.get("category")} score={data.get("memory_score")} content={str(data.get("content", data.get("description", "")))[:120]}')
        sampled += 1

# Category counts
print('\nCategory counts:')
categories = {}
for k in mem_after:
    members = r.zrange(k, 0, -1)
    for m in members:
        data = json.loads(m)
        cat = data.get("category", data.get("type", "unknown"))
        categories[cat] = categories.get(cat, 0) + 1
for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
    print(f'  {cat}: {count}')

# Score distribution
print('\nScore distribution:')
scores = {}
for k in mem_after:
    members = r.zrange(k, 0, -1)
    for m in members:
        data = json.loads(m)
        s = data.get("memory_score", "?")
        scores[s] = scores.get(s, 0) + 1
for s, count in sorted(scores.items()):
    print(f'  score={s}: {count}')
