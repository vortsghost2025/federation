import os, sys

os.environ['CHAR_ID'] = 'char_001'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:16379/1'

_SHARED = 'S:/federation/federation-game/shared'
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from federation_work_loop.core import (
    create_agenda_item, create_capability_request, submit_capability_request,
    update_capability_request_status, record_acceptance_test, _get_redis,
    get_capability_request
)

pair = 'char_001__char_306'
item = create_agenda_item(pair, 'dbg3', 'Task', 'char_001', 'char_001')
req = create_capability_request(pair, item['id'], 'char_001', 'char_306',
    'cap', 'T', 'O', 'B', 'A', [], 'E', 'C', 'Cr', 'Ben', 'Ris')
submit_capability_request(req['request_id'], actor_id='char_001')
update_capability_request_status(req['request_id'], 'acknowledged', actor_id='moderator')
update_capability_request_status(req['request_id'], 'approved', actor_id='moderator')
update_capability_request_status(
    req['request_id'], 'delivered', actor_id='moderator', delivery_reference='ref'
)

r = _get_redis()
key = 'npc_capability_request:' + req['request_id']
data = r.hgetall(key)
print('Status:', data.get('status'))
print('pair_slug:', data.get('pair_slug'))
print('lifecycle_version:', data.get('lifecycle_version'))

r1 = record_acceptance_test(req['request_id'], 'char_001', 'pass', 'Evidence 1')
print('First acceptance:', r1)

r2 = record_acceptance_test(req['request_id'], 'char_306', 'pass', 'Evidence 2')
print('Second acceptance:', r2)
