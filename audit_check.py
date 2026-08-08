import redis, json, time
r = redis.Redis.from_url('redis://redis:6379/0')
audit = r.zrange('llm_audit', 0, 500)
now = time.time()
print('ROWS:', len(audit))
if audit:
    newest = json.loads(audit[-1])
    newest_ts = newest.get('ts', 0)
    print('NEWEST_TS:', newest_ts)
    print('NOW:', now)
    print('AGE_SEC:', now - newest_ts)
    print('--- blank char_id rows ---')
    blank_rows = []
    for a in audit:
        d = json.loads(a)
        if not d.get('char_id'):
            blank_rows.append(d)
    print('blank count:', len(blank_rows))
    for d in blank_rows:
        age = newest_ts - d.get('ts', 0)
        print('ts=', d.get('ts'), 'age_from_newest=', round(age, 1), 'source=', d.get('source'), 'system_path=', d.get('system_path'), 'preview=', d.get('content_preview', '')[:80])
