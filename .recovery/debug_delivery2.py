import os, sys, traceback
from unittest.mock import patch, MagicMock

os.environ['CHAR_ID'] = 'char_001'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:16379/1'

_SHARED = 'S:/federation/federation-game/shared'
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from federation_work_loop.core import (
    create_agenda_item, create_capability_request, submit_capability_request,
    update_capability_request_status, set_pair_messaging_adapter, _get_redis,
    get_capability_request, _on_delivery
)

class _Adapter:
    def send_pair_message(self, **kw):
        print('ADAPTER CALLED:', kw)
        return {'msg_id': 'm1', 'thread_id': kw.get('thread_id', '')}

set_pair_messaging_adapter(_Adapter())

pair = 'char_001__char_306'
item = create_agenda_item(pair, 'dbg2', 'Task', 'char_001', 'char_001')
req = create_capability_request(pair, item['id'], 'char_001', 'char_306',
    'cap', 'T', 'O', 'B', 'A', [], 'E', 'C', 'Cr', 'Ben', 'Ris')
submit_capability_request(req['request_id'], actor_id='char_001')
update_capability_request_status(req['request_id'], 'acknowledged', actor_id='moderator')
update_capability_request_status(req['request_id'], 'approved', actor_id='moderator')

r = _get_redis()
existing = r.hgetall('npc_capability_request:' + req['request_id'])
print('Status before delivery:', existing.get('status'))
print('requester_id:', existing.get('requester_id'))
print('collaborator:', existing.get('collaborating_councilor_id'))
print('pair_slug:', existing.get('pair_slug'))
print('title:', existing.get('title'))
print('agenda_item_id:', existing.get('agenda_item_id'))

# Try calling _on_delivery directly to see what happens
try:
    _on_delivery(existing, 'ref_001')
    print('_on_delivery succeeded')
except Exception as e:
    print('_on_delivery raised:', type(e).__name__, e)
    traceback.print_exc()

# Now try via the status update
result = update_capability_request_status(
    req['request_id'], 'delivered', actor_id='moderator', delivery_reference='ref_001'
)
print('Delivery result:', result)
print('Status after:', get_capability_request(req['request_id'])['status'])
