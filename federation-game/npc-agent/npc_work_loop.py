"""
NPC-agent adapter for federation_work_loop — thin wrapper.
The shared package is made importable via PYTHONPATH=/opt/federation_shared
in the runtime container (and tests add the local shared/ root to sys.path).
"""
import os
import sys

# Local test convenience: ensure the shared package root is on sys.path even
# when PYTHONPATH is not set (e.g. running pytest from the repo). At runtime
# PYTHONPATH=/opt/federation_shared covers this and this path won't exist.
_SHARED_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared")
if os.path.isdir(_SHARED_ROOT) and _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)

from federation_work_loop.core import *  # noqa: F401,F403
from federation_work_loop.core import _pair_slug, _stable_agenda_id, _stable_capability_id  # noqa: F401

# Re-export all public functions for backward compatibility
__all__ = [
    "set_messaging_adapter",
    "set_cognition_scrubber",
    "set_action_scrubber",
    "_scrub_decision_text",
    "_validate_action_category",
    "execute_work_loop_action",
    "record_acceptance_test",
    "AGENCY_ACTIONS",
    "AGENCY_ACTIONS_DISPUTED",
    "get_shared_agenda",
    "get_agenda_item",
    "create_agenda_item",
    "update_agenda_item",
    "claim_ownership",
    "handoff_ownership",
    "get_next_action_owner",
    "create_delegation",
    "attach_delegation_response",
    "create_capability_request",
    "submit_capability_request",
    "get_capability_request",
    "get_capability_requests_for_agenda",
    "update_capability_request_status",
    "get_all_capability_requests",
    "get_agenda_summary",
    "pre_decision_hook",
    "_pair_slug",
    "_stable_agenda_id",
    "_stable_capability_id",
    "PAIR_IDS",
    "AGENDA_ITEM_STATUSES",
    "CAPABILITY_REQUEST_STATUSES",
    "CAPABILITY_REQUEST_TRANSITIONS",
    "ACCEPTANCE_TEST_RESULTS",
]