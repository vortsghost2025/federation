"""
Backend adapter for federation_work_loop — thin wrapper for backend routes.
The shared package is made importable via PYTHONPATH=/opt/federation_shared
in the runtime backend container.
"""
from federation_work_loop.core import *  # noqa: F401,F403

# Re-export all public functions for backward compatibility
__all__ = [
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