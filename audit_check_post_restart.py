import redis, json, sys
started_at_ts = float(sys.argv[1])
r = redis.Redis.from_url('redis://redis:6379/0')
audit = r.zrange('llm_audit', 0, 500)
post = [json.loads(a) for a in audit if json.loads(a).get('ts', 0) > started_at_ts]
print('POST_RESTART_ROWS:', len(post))
source_counts = {}
path_counts = {}
blank_total = 0
blank_by_source = {}
for d in post:
    src = d.get('source', '')
    path = d.get('system_path', '')
    cid = d.get('char_id', '')
    source_counts[src] = source_counts.get(src, 0) + 1
    path_counts[path] = path_counts.get(path, 0) + 1
    if not cid:
        blank_total += 1
        blank_by_source[src] = blank_by_source.get(src, 0) + 1
print('source counts:', source_counts)
print('system_path counts:', path_counts)
print('blank char_id total:', blank_total)
print('blank char_id by source:', blank_by_source)
print('dialogue present:', 'dialogue' in source_counts)
print('any post-restart blank char_id:', blank_total > 0)
