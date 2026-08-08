import json, os, redis
redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
r = redis.Redis.from_url(redis_url)
rows = r.zrevrange('llm_audit', 0, 299)
print('ROWS:', len(rows))
blank_by_source = {}
blank_by_system = {}
blank_by_task = {}
provider_model = {}
examples = []
for raw in rows:
    e = json.loads(raw)
    cid = e.get('char_id')
    if cid == '':
        src = e.get('source') or ''
        sp = e.get('system_path') or ''
        tc = e.get('task_class') or ''
        pm = (e.get('provider') or '', e.get('model') or '')
        blank_by_source[src] = blank_by_source.get(src, 0) + 1
        blank_by_system[sp] = blank_by_system.get(sp, 0) + 1
        blank_by_task[tc] = blank_by_task.get(tc, 0) + 1
        provider_model[pm] = provider_model.get(pm, 0) + 1
        if len(examples) < 10:
            examples.append(e)
print('Blank by source:', dict(blank_by_source))
print('Blank by system_path:', dict(blank_by_system))
print('Blank by task_class:', dict(blank_by_task))
print('Top provider/model for blank:', sorted(provider_model.items(), key=lambda x: x[1], reverse=True)[:5])
print('Example blank rows:')
for ex in examples:
    print(json.dumps(ex))