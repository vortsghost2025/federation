import redis, time

r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)

# Wait for a new tick by watching sim_last_tick
last_tick = r.get('sim_last_tick')
print('Current sim_last_tick:', last_tick)
print('Waiting for new tick...')

for i in range(60):
    time.sleep(5)
    new_tick = r.get('sim_last_tick')
    if new_tick != last_tick:
        print('New tick detected:', new_tick)
        break
else:
    print('No new tick after 300s')

mem = list(r.scan_iter('npc_memory:*'))
summ = list(r.scan_iter('npc_memory_summary:*'))
print('POST-TICK npc_memory keys:', len(mem))
print('POST-TICK npc_memory_summary keys:', len(summ))

# Top keys by zcard
print('\nTop npc_memory keys by zcard:')
key_counts = [(k, r.zcard(k)) for k in mem]
key_counts.sort(key=lambda x: -x[1])
for k, count in key_counts[:10]:
    print(f'  {k}: {count}')

# Sample 3 events from different NPCs
print('\nSample events:')
sampled = 0
for k, count in key_counts:
    if sampled >= 3:
        break
    members = r.zrevrange(k, 0, 0)
    if members:
        import json
        data = json.loads(members[0])
        print(f'  {k}: type={data.get("type")} category={data.get("category")} content={str(data.get("content", data.get("description", "")))[:100]}')
        sampled += 1
