import redis

r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)
mem = list(r.scan_iter('npc_memory:*'))
summ = list(r.scan_iter('npc_memory_summary:*'))
print('PRE-TICK npc_memory keys:', len(mem))
print('PRE-TICK npc_memory_summary keys:', len(summ))
for k in mem[:10]:
    print(' ', k, 'zcard:', r.zcard(k))
