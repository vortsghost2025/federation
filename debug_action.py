import sys, os, json
from unittest.mock import patch

sys.path.insert(0, r'S:\federation\federation-game\npc-agent')
_shared_path = os.path.join(os.path.dirname(os.path.abspath(r'S:\federation\federation-game\npc-agent\test_npc_work_loop.py')), "..", "shared")
if os.path.isdir(_shared_path) and _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

os.environ['CHAR_ID'] = 'char_001'
os.environ['REDIS_URL'] = 'redis://redis:6379/0'

import types
sys.modules.setdefault('redis', types.SimpleNamespace(
    Redis=lambda **kw: None,
    from_url=lambda *a, **kw: None,
))

# Import test setup
exec(open(r'S:\federation\federation-game\npc-agent\test_npc_work_loop.py').read().split('class Test')[0].replace('__file__', r'"S:\federation\federation-game\npc-agent\test_npc_work_loop.py"'))

from federation_work_loop.core import execute_work_loop_action, create_agenda_item, claim_ownership, set_action_scrubber

PAIR = "char_001__char_306"

# Apply the same patch as tests
fake = FakeRedis()
with patch("federation_work_loop.core._get_redis", return_value=fake):
    item = create_agenda_item(PAIR, 'scrub_task', 'Scrub me', 'char_001')
    claim_ownership(PAIR, item['id'], 'char_001')
    set_action_scrubber(lambda t: t.upper())
    result = execute_work_loop_action('agenda_decision', {'actor_id': 'char_001', 'pair_slug': PAIR, 'agenda_id': item['id'], 'decision': 'test decision'})
    print(json.dumps(result, indent=2))