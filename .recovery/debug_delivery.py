import os, sys, types
from unittest.mock import patch, MagicMock

os.environ['CHAR_ID'] = 'char_001'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:16379/1'

_SHARED = 'S:/federation/federation-game/shared'
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from federation_work_loop.core import (
    create_agenda_item, create_capability_request, submit_capability_request,
    update_capability_request_status, set_pair_messaging_adapter, _get_redis,
    get_capability_request
)

class _Adapter:
    def send_pair_message(self, **kw):
        print('ADAPTER CALLED:', kw)
        return {'msg_id': 'm1', 'thread_id': kw.get('thread_id', '')}

set_pair_messaging_adapter(_Adapter())

pair = 'char_001__char_306'
item = create_agenda_item(pair, 'dbg', 'Task', 'char_001', 'char_001')
req = create_capability_request(pair, item['id'], 'char_001', 'char_306',
    'cap', 'T', 'O', 'B', 'A', [], 'E', 'C', 'Cr', 'Ben', 'Ris')
submit_capability_request(req['request_id'], actor_id='char_001')

r = _get_redis()
existing = r.hgetall('npc_capability_request:' + req['request_id'])
print('Redis raw keys:', list(existing.keys()))
print('requester_id:', existing.get('requester_id'))
print('collaborating_councilor_id:', existing.get('collaborating_councilor_id'))

result = update_capability_request_status(
    req['request_id'], 'delivered', actor_id='moderator', delivery_reference='ref'
)
print('Result:', result)
print('Status:', get_capability_request(req['request_id'])['status'])
