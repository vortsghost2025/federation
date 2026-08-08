"""
Federation Work Loop — Shared persistent agenda for the persistent councilor pair.

Authoritative implementation lives in shared/federation_work_loop/.
Both backend routes and npc-agent import from here.

Redis keys (no TTL — durable, same as institutions.py workflow keys):
    npc_pair:{pair_slug}:agenda              — ZSET: agenda_id -> created_ts
    npc_pair:{pair_slug}:agenda:{agenda_id}  — HASH: agenda item fields
    npc_capability_request:{request_id}      — HASH: capability request fields
    npc_capability_requests:index            — ZSET: request_id -> created_ts
    npc_capability_requests:stable:{stable_id} — STRING: request_id (dedup)
    npc_delegation:processed:{msg_id}        — STRING: marker for processed responses
"""

import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import redis

logger = logging.getLogger("federation_work_loop")

_messaging_adapter = None
_pair_messaging_adapter = None


def set_messaging_adapter(adapter):
    """Inject a messaging adapter from the runtime layer.

    The adapter must provide ``adapter.send_message(**kwargs)`` with the same
    signature as ``backend/npc_messaging.py:send_message()``.  Shared domain
    code calls this adapter instead of importing ``npc_messaging`` directly.
    """
    global _messaging_adapter
    if adapter is not None and not callable(getattr(adapter, "send_message", None)):
        raise TypeError("messaging adapter must expose a send_message callable")
    _messaging_adapter = adapter


def set_pair_messaging_adapter(adapter):
    """Inject a pair messaging adapter for persistent councilor notifications.

    The adapter must provide ``adapter.send_pair_message(from_char_id, from_char_name,
    to_char_id, subject, body, thread_id)`` using the pair LIST schema:
    ``npc_messages:{to_char_id}:inbox`` and ``npc_messages:{from_char_id}:sent``.
    """
    global _pair_messaging_adapter
    if adapter is not None and not callable(getattr(adapter, "send_pair_message", None)):
        raise TypeError("pair messaging adapter must expose a send_pair_message callable")
    _pair_messaging_adapter = adapter


def _send_message(**kwargs):
    """Send a message through the injected adapter, or log a warning."""
    if _messaging_adapter is not None:
        return _messaging_adapter.send_message(**kwargs)
    logger.warning("_send_message: no messaging adapter set; message not sent")
    try:
        from npc_messaging import send_message as _fallback
        return _fallback(**kwargs)
    except ImportError:
        logger.warning("_send_message: npc_messaging unavailable (shared domain)")
    return None


def _send_pair_message(
    from_char_id: str,
    from_char_name: str,
    to_char_id: str,
    subject: str,
    body: str,
    thread_id: str = "",
) -> Optional[Dict[str, str]]:
    """Send a message to a persistent councilor using the pair LIST schema.

    Uses the injected pair messaging adapter. Falls back to direct Redis
    LIST operations if no adapter is set (for test compatibility).
    """
    if _pair_messaging_adapter is not None:
        return _pair_messaging_adapter.send_pair_message(
            from_char_id=from_char_id,
            from_char_name=from_char_name,
            to_char_id=to_char_id,
            subject=subject,
            body=body,
            thread_id=thread_id,
        )
    logger.warning("_send_pair_message: no pair messaging adapter set; message not sent")
    try:
        import json
        import time
        import uuid
        r = _get_redis()
        ts = int(time.time())
        msg_id = str(uuid.uuid4())
        msg = {
            "id": msg_id,
            "msg_id": msg_id,
            "from_char_id": from_char_id,
            "from_name": from_char_name,
            "to_char_id": to_char_id,
            "to_name": to_char_id,
            "subject": subject,
            "body": body,
            "type": "system_notification",
            "read": False,
            "created_at": ts,
            "ts": ts,
            "thread_id": thread_id or f"thread_delivery_{msg_id}",
        }
        r.rpush(f"npc_messages:{to_char_id}:inbox", json.dumps(msg))
        r.rpush(f"npc_messages:{from_char_id}:sent", json.dumps(msg))
        return {"msg_id": msg_id, "thread_id": msg["thread_id"]}
    except Exception as e:
        logger.warning("_send_pair_message fallback failed: %s", e)
    return None

# ── Runtime Action Adapter ────────────────────────────────────────────

# Bounded work-loop actions (10 actions). All external callers must go through
# execute_work_loop_action(). No direct domain function calls from runtime.
_WORK_LOOP_ACTIONS = frozenset({
    "agenda_create",
    "agenda_claim",
    "agenda_handoff",
    "agenda_review",
    "agenda_decision",
    "agenda_block",
    "agenda_delegate",
    "capability_request_draft",
    "capability_request_submit",
    "acceptance_test_record",
    "area_found",
})

_action_scrubber = None


def set_action_scrubber(scrubber):
    """Inject a callable that enforces fourth-wall / placeholder / duplicate
    rejection on text fields in work-loop actions.

    The callable receives ``(text: str)`` and returns the cleaned string.
    """
    global _action_scrubber
    _action_scrubber = scrubber


def _scrub_action_text(text: str) -> str:
    if _action_scrubber is not None:
        return _action_scrubber(text)
    return text


def _validate_work_loop_action(action: str) -> bool:
    return action in _WORK_LOOP_ACTIONS


def _validate_pair_member(actor_id: str) -> bool:
    return actor_id in PAIR_IDS


def _validate_councilor_role(actor_id: str) -> str:
    if actor_id in {"moderator", "operator"}:
        return "moderator"
    if actor_id in PAIR_IDS:
        return "councilor"
    return "external"


def _get_owned_agenda_id(pair_slug: str, actor_id: str) -> Optional[str]:
    """Return the agenda_id currently owned by actor_id, or None."""
    agenda = get_shared_agenda(pair_slug)
    for item in agenda:
        if item.get("owner") == actor_id and item.get("status") not in {"completed", "rejected"}:
            return item.get("id")
    return None


def execute_work_loop_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a bounded work-loop action with full validation.

    Returns: {"ok": bool, "action": str, "result": Any, "error": Optional[str]}
    """
    if not _validate_work_loop_action(action):
        return {"ok": False, "action": action, "result": None, "error": "unsupported_action"}

    # Common validations
    actor_id = payload.get("actor_id", "")
    if not actor_id:
        return {"ok": False, "action": action, "result": None, "error": "missing_actor_id"}

    pair_slug = payload.get("pair_slug", "")
    if not pair_slug or not _validate_pair_member(actor_id):
        return {"ok": False, "action": action, "result": None, "error": "invalid_pair_or_actor"}

    # Scrub text fields through injected callback
    for key in ("objective", "reason", "description", "body", "evidence", "mandate", "scope", "title", "decision"):
        if key in payload and isinstance(payload[key], str):
            payload[key] = _scrub_action_text(payload[key])

    # Dispatch to action handler
    try:
        if action == "agenda_create":
            return _action_agenda_create(pair_slug, actor_id, payload)
        elif action == "agenda_claim":
            return _action_agenda_claim(pair_slug, actor_id, payload)
        elif action == "agenda_handoff":
            return _action_agenda_handoff(pair_slug, actor_id, payload)
        elif action == "agenda_review":
            return _action_agenda_review(pair_slug, actor_id, payload)
        elif action == "agenda_decision":
            return _action_agenda_decision(pair_slug, actor_id, payload)
        elif action == "agenda_block":
            return _action_agenda_block(pair_slug, actor_id, payload)
        elif action == "agenda_delegate":
            return _action_agenda_delegate(pair_slug, actor_id, payload)
        elif action == "capability_request_draft":
            return _action_capability_request_draft(pair_slug, actor_id, payload)
        elif action == "capability_request_submit":
            return _action_capability_request_submit(pair_slug, actor_id, payload)
        elif action == "acceptance_test_record":
            return _action_acceptance_test_record(pair_slug, actor_id, payload)
        elif action == "area_found":
            return _action_area_found(pair_slug, actor_id, payload)
    except Exception as e:
        logger.exception("[%s] Action %s raised: %s", actor_id, action, e)
        return {"ok": False, "action": action, "result": None, "error": f"internal_error: {e}"}

    return {"ok": False, "action": action, "result": None, "error": "unhandled_action"}


# ── Action Handlers ──────────────────────────────────────────────────

def _action_agenda_create(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new agenda item. Blocks if actor already owns active work."""
    owned = _get_owned_agenda_id(pair_slug, actor_id)
    if owned:
        return {"ok": False, "action": "agenda_create", "result": None,
                "error": "already_owns_work", "owned_agenda_id": owned}

    agenda_key = payload.get("agenda_key", "")
    objective = payload.get("objective", "")
    if not agenda_key or not objective:
        return {"ok": False, "action": "agenda_create", "result": None, "error": "missing_required_fields"}

    item = create_agenda_item(pair_slug, agenda_key, objective, actor_id)
    if item.get("_error"):
        return {"ok": False, "action": "agenda_create", "result": None, "error": item["_error"]}
    return {"ok": True, "action": "agenda_create", "result": item, "error": None}


def _action_agenda_claim(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically claim ownership of an agenda item."""
    agenda_id = payload.get("agenda_id", "")
    if not agenda_id:
        return {"ok": False, "action": "agenda_claim", "result": None, "error": "missing_agenda_id"}

    # Block if actor already owns different active work
    owned = _get_owned_agenda_id(pair_slug, actor_id)
    if owned and owned != agenda_id:
        return {"ok": False, "action": "agenda_claim", "result": None,
                "error": "already_owns_other_work", "owned_agenda_id": owned}

    success = claim_ownership(pair_slug, agenda_id, actor_id)
    if not success:
        item = get_agenda_item(pair_slug, agenda_id)
        if not item:
            return {"ok": False, "action": "agenda_claim", "result": None, "error": "agenda_not_found"}
        return {"ok": False, "action": "agenda_claim", "result": None,
                "error": "claim_failed", "current_owner": item.get("owner")}
    return {"ok": True, "action": "agenda_claim", "result": get_agenda_item(pair_slug, agenda_id), "error": None}


def _action_agenda_handoff(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically hand ownership to another councilor."""
    agenda_id = payload.get("agenda_id", "")
    new_owner = payload.get("new_owner", "")
    expected_version = payload.get("expected_version", "")
    if not agenda_id or not new_owner:
        return {"ok": False, "action": "agenda_handoff", "result": None, "error": "missing_required_fields"}
    if new_owner not in PAIR_IDS:
        return {"ok": False, "action": "agenda_handoff", "result": None, "error": "invalid_new_owner"}

    success = handoff_ownership(pair_slug, agenda_id, new_owner, actor_id, expected_version)
    if not success:
        item = get_agenda_item(pair_slug, agenda_id)
        if not item:
            return {"ok": False, "action": "agenda_handoff", "result": None, "error": "agenda_not_found"}
        return {"ok": False, "action": "agenda_handoff", "result": None,
                "error": "handoff_failed", "current_owner": item.get("owner"),
                "current_version": item.get("owner_version")}
    return {"ok": True, "action": "agenda_handoff", "result": get_agenda_item(pair_slug, agenda_id), "error": None}


def _action_agenda_review(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Review an agenda item — read-only access to full item."""
    agenda_id = payload.get("agenda_id", "")
    if not agenda_id:
        return {"ok": False, "action": "agenda_review", "result": None, "error": "missing_agenda_id"}
    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return {"ok": False, "action": "agenda_review", "result": None, "error": "agenda_not_found"}
    return {"ok": True, "action": "agenda_review", "result": item, "error": None}


def _action_agenda_decision(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Record a decision on an owned agenda item."""
    agenda_id = payload.get("agenda_id", "")
    decision = payload.get("decision", "")
    if not agenda_id or not decision:
        return {"ok": False, "action": "agenda_decision", "result": None, "error": "missing_required_fields"}

    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return {"ok": False, "action": "agenda_decision", "result": None, "error": "agenda_not_found"}
    if item.get("owner") != actor_id:
        return {"ok": False, "action": "agenda_decision", "result": None, "error": "not_owner"}

    decisions = item.get("decisions", [])
    if isinstance(decisions, str):
        import json
        decisions = json.loads(decisions) if decisions else []
    decisions.append({"actor": actor_id, "decision": decision, "timestamp": _now_iso()})
    updated = update_agenda_item(pair_slug, agenda_id, decisions=decisions)
    return {"ok": True, "action": "agenda_decision", "result": updated, "error": None}


def _action_agenda_block(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Block an agenda item with a reason."""
    agenda_id = payload.get("agenda_id", "")
    blocker = payload.get("blocker", "")
    if not agenda_id or not blocker:
        return {"ok": False, "action": "agenda_block", "result": None, "error": "missing_required_fields"}

    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return {"ok": False, "action": "agenda_block", "result": None, "error": "agenda_not_found"}
    if item.get("owner") != actor_id:
        return {"ok": False, "action": "agenda_block", "result": None, "error": "not_owner"}

    updated = update_agenda_item(pair_slug, agenda_id, status="blocked", blocker=blocker,
                                 next_action=f"Blocked by {actor_id}: {blocker}")
    return {"ok": True, "action": "agenda_block", "result": updated, "error": None}


def _action_agenda_delegate(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a delegation from an owned agenda item."""
    agenda_id = payload.get("agenda_id", "")
    target_npc_id = payload.get("target_npc_id", "")
    question = payload.get("question", "")
    reason = payload.get("reason", "")
    expected_format = payload.get("expected_format", "")
    if not agenda_id or not target_npc_id or not question or not reason or not expected_format:
        return {"ok": False, "action": "agenda_delegate", "result": None, "error": "missing_required_fields"}

    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return {"ok": False, "action": "agenda_delegate", "result": None, "error": "agenda_not_found"}
    if item.get("owner") != actor_id:
        return {"ok": False, "action": "agenda_delegate", "result": None, "error": "not_owner"}
    if target_npc_id in PAIR_IDS:
        return {"ok": False, "action": "agenda_delegate", "result": None, "error": "cannot_delegate_to_pair"}

    from_char_name = payload.get("from_char_name", actor_id)
    delegation = create_delegation(pair_slug, agenda_id, actor_id, from_char_name,
                                   target_npc_id, question, reason, expected_format)
    if not delegation:
        return {"ok": False, "action": "agenda_delegate", "result": None, "error": "delegation_failed"}
    return {"ok": True, "action": "agenda_delegate", "result": delegation, "error": None}


def _action_capability_request_draft(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a capability request draft."""
    agenda_id = payload.get("agenda_id", "")
    if not agenda_id:
        return {"ok": False, "action": "capability_request_draft", "result": None, "error": "missing_agenda_id"}

    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return {"ok": False, "action": "capability_request_draft", "result": None, "error": "agenda_not_found"}

    required = ["capability_key", "title", "objective", "blocker", "attempts",
                "consulted_npcs", "evidence", "requested_change",
                "acceptance_criteria", "expected_benefit", "implementation_risks"]
    for field in required:
        if field not in payload:
            return {"ok": False, "action": "capability_request_draft", "result": None, "error": f"missing_field: {field}"}

    request = create_capability_request(
        pair_slug=pair_slug,
        agenda_id=agenda_id,
        requester_id=actor_id,
        collaborating_councilor_id=payload.get("collaborating_councilor_id", ""),
        capability_key=payload["capability_key"],
        title=payload["title"],
        objective=payload["objective"],
        blocker=payload["blocker"],
        attempts=payload["attempts"],
        consulted_npcs=payload["consulted_npcs"],
        evidence=payload["evidence"],
        requested_change=payload["requested_change"],
        acceptance_criteria=payload["acceptance_criteria"],
        expected_benefit=payload["expected_benefit"],
        implementation_risks=payload["implementation_risks"],
        priority=payload.get("priority", "medium"),
    )
    if request.get("_error"):
        return {"ok": False, "action": "capability_request_draft", "result": None, "error": request["_error"]}
    return {"ok": True, "action": "capability_request_draft", "result": request, "error": None}


def _action_capability_request_submit(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a capability request for review."""
    request_id = payload.get("request_id", "")
    if not request_id:
        return {"ok": False, "action": "capability_request_submit", "result": None, "error": "missing_request_id"}

    success = submit_capability_request(request_id, actor_id)
    if not success:
        req = get_capability_request(request_id)
        if not req:
            return {"ok": False, "action": "capability_request_submit", "result": None, "error": "request_not_found"}
        return {"ok": False, "action": "capability_request_submit", "result": None,
                "error": "submit_failed", "current_status": req.get("status")}
    return {"ok": True, "action": "capability_request_submit", "result": get_capability_request(request_id), "error": None}


def _action_acceptance_test_record(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Record an acceptance test result for a capability request (pair acceptance)."""
    request_id = payload.get("request_id", "")
    result = payload.get("result", "")
    evidence = payload.get("evidence", "")
    expected_version = payload.get("expected_version", "")
    if not request_id or result not in ACCEPTANCE_TEST_RESULTS:
        return {"ok": False, "action": "acceptance_test_record", "result": None, "error": "missing_or_invalid_fields"}

    if actor_id not in PAIR_IDS:
        return {"ok": False, "action": "acceptance_test_record", "result": None, "error": "only_councilors_may_record"}

    key = f"npc_capability_request:{request_id}"
    r = _get_redis()
    existing = r.hgetall(key)
    if not existing:
        return {"ok": False, "action": "acceptance_test_record", "result": None, "error": "request_not_found"}

    current_status = existing.get("status", "")
    if current_status not in {"delivered", "verification_pending"}:
        return {"ok": False, "action": "acceptance_test_record", "result": None,
                "error": f"invalid_status_for_acceptance: {current_status}"}

    # Version check
    if expected_version and existing.get("lifecycle_version", "") != expected_version:
        return {"ok": False, "action": "acceptance_test_record", "result": None,
                "error": "version_mismatch", "current_version": existing.get("lifecycle_version", "")}

    # Atomic: record acceptance in pair set
    acceptance_key = f"npc_pair:{pair_slug}:capability_acceptance:{request_id}"
    was_new = r.sadd(acceptance_key, actor_id)
    if was_new == 0:
        # Already recorded by this councilor - idempotent
        return {"ok": True, "action": "acceptance_test_record", "result": {"idempotent": True}, "error": None}

    # Store the evidence and result per-councilor
    r.hset(f"{acceptance_key}:{actor_id}", mapping={
        "result": result,
        "evidence": evidence,
        "timestamp": _now_iso(),
        "lifecycle_version": existing.get("lifecycle_version", ""),
    })

    # If both have passed and status is verification_pending, allow moderator to verify
    if result == "pass":
        passed_count = r.scard(acceptance_key)
        if passed_count >= 2 and current_status == "verification_pending":
            # Status remains verification_pending until moderator verifies
            pass
    elif result in {"fail", "partial"}:
        # Reopen agenda for retest
        _reopen_agenda_for_retest(existing, result)

    return {"ok": True, "action": "acceptance_test_record", "result": {"recorded": True, "passed_count": r.scard(acceptance_key)}, "error": None}


# ── Area / World Expansion ──────────────────────────────────────────
# Lets the persistent councilor pair FOUND new areas/sectors in their
# world. Stored durably (no TTL) so the map they build persists and can
# later be surfaced alongside the procedural universe.

def _areas_key(pair_slug: str) -> str:
    return f"npc_pair:{pair_slug}:areas"


def _normalize_area_id(raw: str) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(raw).strip().lower())
    return cleaned[:48]


def _action_area_found(pair_slug: str, actor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Found a new area/sector in the pair's world. Durable, pair-scoped."""
    if actor_id not in PAIR_IDS:
        return {"ok": False, "action": "area_found", "result": None, "error": "only_councilors_may_found"}

    raw_id = payload.get("area_id", "")
    area_id = _normalize_area_id(raw_id)
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    if not area_id or not name or not description:
        return {"ok": False, "action": "area_found", "result": None,
                "error": "missing_required_fields", "required": ["area_id", "name", "description"]}

    record = {
        "area_id": area_id,
        "name": name,
        "description": description,
        "region_type": (payload.get("region_type") or "frontier").strip(),
        "resource_profile": (payload.get("resource_profile") or "mixed").strip(),
        "danger_level": int(payload.get("danger_level", 5) or 5),
        "x": float(payload.get("x", 0) or 0),
        "y": float(payload.get("y", 0) or 0),
        "adjacent_sector_ids": list(payload.get("adjacent_sector_ids", []) or []),
        "founded_by": actor_id,
        "pair_slug": pair_slug,
        "created_at": _now_iso(),
    }

    r = _get_redis()
    key = _areas_key(pair_slug)
    if r.hexists(key, area_id):
        existing = json.loads(r.hget(key, area_id) or "{}")
        # Push a system notification so the NPC knows the area is already on the map.
        try:
            existing_areas = get_areas(pair_slug)
            area_summary = ", ".join(
                f"{a['area_id']} ({a['name']}, founded_by={a['founded_by']})"
                for a in existing_areas
            ) or "(no areas yet)"
            notification = {
                "type": "area_already_founded",
                "area_id": area_id,
                "name": existing.get("name", name),
                "founded_by": existing.get("founded_by", "?"),
                "created_at": existing.get("created_at", ""),
                "existing_areas": area_summary,
                "message": (
                    f"Area '{area_id}' is already on your shared map "
                    f"(founded by {existing.get('founded_by', '?')}). "
                    f"Existing areas: {area_summary}. "
                    f"Propose a NEW area with a different slug, name, "
                    f"or coordinates instead of re-using this one."
                ),
            }
            r.rpush(f"npc:system_notifications:{actor_id}", json.dumps(notification))
            logger.info("[%s] area_found idempotent: %s already on map", actor_id, area_id)
        except Exception as e:
            logger.warning("[%s] area_found idempotent notification failed: %s", actor_id, e)
        return {"ok": True, "action": "area_found", "result": existing, "error": None, "idempotent": True}

    r.hset(key, area_id, json.dumps(record))
    try:
        notification = {
            "type": "area_founded",
            "area_id": area_id,
            "name": name,
            "founded_by": actor_id,
            "message": f"You founded '{name}' ({area_id}). It is now on the shared map.",
        }
        r.rpush(f"npc:system_notifications:{actor_id}", json.dumps(notification))
    except Exception as e:
        logger.warning("[%s] area_found confirmation notification failed: %s", actor_id, e)
    return {"ok": True, "action": "area_found", "result": record, "error": None}


def get_areas(pair_slug: str) -> List[Dict[str, Any]]:
    """Return all areas founded by the pair (oldest-first)."""
    r = _get_redis()
    key = _areas_key(pair_slug)
    raws = r.hgetall(key)
    out = []
    for raw in raws.values():
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    out.sort(key=lambda a: a.get("created_at", ""))
    return out


def get_area(pair_slug: str, area_id: str) -> Optional[Dict[str, Any]]:
    area_id = _normalize_area_id(area_id)
    if not area_id:
        return None
    r = _get_redis()
    raw = r.hget(_areas_key(pair_slug), area_id)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── Cognition Action Adapter (Legacy) ────────────────────────────────

AGENCY_ACTIONS = frozenset({
    "create_artifact",
    "write_code",
    "send_message",
    "read_artifacts",
    "investigate",
    "rest",
    "self_improve",
    "create_institution",
    "propose_role",
    "submit_to_institution",
    "request_capability",
})

AGENCY_ACTIONS_DISPUTED = frozenset({
    "send_message", "create_institution", "propose_role", "submit_to_institution",
})

_cognition_scrubber = None


def set_cognition_scrubber(scrubber):
    """Inject a callable that enforces fourth-wall / placeholder / duplicate
    rejection before the work-loop validates a cognition decision.

    The callable receives ``(text: str)`` and returns the cleaned string.
    """
    global _cognition_scrubber
    _cognition_scrubber = scrubber


def _scrub_decision_text(text: str) -> str:
    if _cognition_scrubber is not None:
        return _cognition_scrubber(text)
    return text


def _validate_action_category(category: str) -> bool:
    return category in AGENCY_ACTIONS


# ── Redis Constants ─────────────────────────────────────────────────

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
PAIR_IDS = {"char_001", "char_306"}

AGENDA_ITEM_STATUSES = frozenset({
    "proposed", "investigating", "delegated", "blocked", "requested", "completed", "rejected"
})

AGENDA_KEY_PATTERN = re.compile(r"^[a-z0-9_]{3,64}$")

CAPABILITY_REQUEST_STATUSES = frozenset({
    "draft", "submitted", "acknowledged", "approved", "rejected",
    "delivered", "verification_pending", "verified"
})

CAPABILITY_REQUEST_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {"acknowledged", "rejected"},
    "acknowledged": {"approved", "rejected"},
    "rejected": {"draft"},
    "approved": {"delivered"},
    "delivered": {"verification_pending"},
    "verification_pending": {"verified", "delivered"},
    "verified": set(),
}

ACCEPTANCE_TEST_RESULTS = frozenset({"pass", "fail", "partial"})


def _get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)


def _pair_slug(char_a: str, char_b: str) -> str:
    return "__".join(sorted([char_a, char_b]))


def _agenda_index_key(pair_slug: str) -> str:
    return f"npc_pair:{pair_slug}:agenda"


def _agenda_item_key(pair_slug: str, agenda_id: str) -> str:
    return f"npc_pair:{pair_slug}:agenda:{agenda_id}"


def _capability_request_key(request_id: str) -> str:
    return f"npc_capability_request:{request_id}"


def _capability_index_key() -> str:
    return "npc_capability_requests:index"


def _capability_stable_key(stable_id: str) -> str:
    return f"npc_capability_requests:stable:{stable_id}"


def _delegation_processed_key(msg_id: str) -> str:
    return f"npc_delegation:processed:{msg_id}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _now_ts() -> float:
    return time.time()


def _stable_agenda_id(pair_slug: str, agenda_key: str) -> str:
    import hashlib
    content = f"{pair_slug}:{agenda_key}"
    return f"agenda_{hashlib.sha256(content.encode()).hexdigest()[:16]}"


def _stable_capability_id(agenda_id: str, capability_key: str) -> str:
    import hashlib
    content = f"{agenda_id}:{capability_key}"
    return f"capreq_{hashlib.sha256(content.encode()).hexdigest()[:16]}"


# ── Lua: Atomic ownership claim ────────────────────────────────────

_CLAIM_LUA = """
local key = KEYS[1]
local claimer = ARGV[1]
local expected_version = ARGV[2]
local now = ARGV[3]

if redis.call('EXISTS', key) == 0 then
    return 0
end

local current = redis.call('HGET', key, 'owner')
local current_version = redis.call('HGET', key, 'owner_version') or '0'

if current == claimer then
    return 2
end
if expected_version ~= '' and expected_version ~= '0' and current_version ~= expected_version then
    return 0
end
if current and current ~= '' then
    return 0
end
redis.call('HSET', key, 'owner', claimer, 'owner_version', tostring(tonumber(current_version) + 1), 'owner_claimed_at', now)
return 1
"""

_HANDOFF_LUA = """
local key = KEYS[1]
local new_owner = ARGV[1]
local expected_owner = ARGV[2]
local expected_version = ARGV[3]
local now = ARGV[4]

if redis.call('EXISTS', key) == 0 then
    return 0
end

local current_owner = redis.call('HGET', key, 'owner')
local current_version = redis.call('HGET', key, 'owner_version') or '0'

if current_owner ~= expected_owner then
    return 0
end
if expected_version ~= '' and current_version ~= expected_version then
    return 0
end
redis.call('HSET', key, 'owner', new_owner, 'owner_version', tostring(tonumber(current_version) + 1), 'owner_claimed_at', now)
return 1
"""

_LIFECYCLE_TRANSITION_LUA = """
local key = KEYS[1]
local request_id = ARGV[1]
local new_status = ARGV[2]
local expected_status = ARGV[3]
local expected_version = ARGV[4]
local actor_id = ARGV[5]
local reason = ARGV[6]
local delivery_reference = ARGV[7]
local acceptance_result = ARGV[8]
local acceptance_evidence = ARGV[9]
local actor_role = ARGV[10]
local now = ARGV[11]

local current_status = redis.call('HGET', key, 'status')
local current_version = redis.call('HGET', key, 'lifecycle_version') or '0'

if current_status ~= expected_status then
    return {0, "status_mismatch", current_status}
end
if expected_version ~= '' and current_version ~= expected_version then
    return {0, "version_mismatch", current_version}
end

local transitions = cjson.decode(redis.call('HGET', key, 'transitions') or '[]')
table.insert(transitions, {
    from = expected_status,
    to = new_status,
    actor = actor_id,
    role = actor_role,
    reason = reason,
    timestamp = now
})

redis.call('HSET', key,
    'status', new_status,
    'lifecycle_version', tostring(tonumber(current_version) + 1),
    'transitions', cjson.encode(transitions),
    'updated_at', now,
    'updated_ts', ARGV[11],
    'delivery_reference', delivery_reference,
    'acceptance_test_result', acceptance_result,
    'acceptance_test_evidence', acceptance_evidence
)
return {1, "ok", new_status}
"""

# ── Lua: Atomic acceptance test recording ────────────────────────────
# Records a councilor's acceptance test result with full validation.
# When the second distinct PASS is recorded while status is delivered,
# atomically transitions to verification_pending.
#
# KEYS[1] = capability request key
# ARGV[1] = request_id
# ARGV[2] = councilor_id (must be in PAIR_IDS)
# ARGV[3] = result (pass/fail/partial)
# ARGV[4] = evidence
# ARGV[5] = expected_lifecycle_version
# ARGV[6] = pair_slug
# ARGV[7] = now (ISO timestamp)
# ARGV[8] = requester_id (from request hash in Redis)
# ARGV[9] = collaborating_councilor_id (from request hash in Redis)
#
# Returns:
#   success: {1, "ok", passed_count, idempotent, transitioned}
#   failure: {0, error_code, detail}

_ACCEPTANCE_TEST_LUA = """
local key = KEYS[1]
local request_id = ARGV[1]
local councilor_id = ARGV[2]
local result = ARGV[3]
local evidence = ARGV[4]
local expected_version = ARGV[5]
local pair_slug = ARGV[6]
local now = ARGV[7]
local pair_a = ARGV[8]
local pair_b = ARGV[9]

-- 1. Validate request exists
local current_status = redis.call('HGET', key, 'status')
if not current_status or current_status == '' then
    return {0, "request_not_found", ""}
end

-- 2. Validate status
if current_status ~= 'delivered' and current_status ~= 'verification_pending' then
    return {0, "invalid_status_for_acceptance", current_status}
end

-- 3. Validate result
if result ~= 'pass' and result ~= 'fail' and result ~= 'partial' then
    return {0, "invalid_result", result}
end

-- 4. Validate expected lifecycle version
local current_version = redis.call('HGET', key, 'lifecycle_version') or '0'
if expected_version ~= '' and current_version ~= expected_version then
    return {0, "version_mismatch", current_version}
end

-- 5. Validate councilor belongs to pair
if councilor_id ~= pair_a and councilor_id ~= pair_b then
    return {0, "councilor_not_in_pair", councilor_id}
end

-- 6. Record acceptance in pair set
local acceptance_key = 'npc_pair:' .. pair_slug .. ':capability_acceptance:' .. request_id
local was_new = redis.call('SADD', acceptance_key, councilor_id)

-- 7. Check idempotency / conflicting replacement
if was_new == 0 then
    local detail_key = acceptance_key .. ':' .. councilor_id
    local existing_result = redis.call('HGET', detail_key, 'result')
    local existing_evidence = redis.call('HGET', detail_key, 'evidence')
    if existing_result ~= result or existing_evidence ~= evidence then
        return {0, "conflicting_acceptance", existing_result}
    end
    local passed_count = redis.call('SCARD', acceptance_key)
    return {1, "ok", passed_count, 1, 0}
end

-- 8. Persist acceptance detail record
local detail_key = acceptance_key .. ':' .. councilor_id
redis.call('HSET', detail_key,
    'result', result,
    'evidence', evidence,
    'timestamp', now,
    'lifecycle_version', current_version)

-- 9. Count PASS records only (not merely councilor membership)
local members = redis.call('SMEMBERS', acceptance_key)
local pass_count = 0
for _, member in ipairs(members) do
    local member_result = redis.call('HGET', acceptance_key .. ':' .. member, 'result')
    if member_result == 'pass' then
        pass_count = pass_count + 1
    end
end

-- 10. If second distinct PASS while status is delivered, atomically transition
if result == 'pass' and current_status == 'delivered' and pass_count == 2 then
    local transitions = cjson.decode(redis.call('HGET', key, 'transitions') or '[]')
    table.insert(transitions, {
        from = 'delivered',
        to = 'verification_pending',
        actor = councilor_id,
        role = 'councilor',
        reason = 'Both councilors passed acceptance tests',
        timestamp = now
    })
    local new_version = tostring(tonumber(current_version) + 1)
    redis.call('HSET', key,
        'status', 'verification_pending',
        'lifecycle_version', new_version,
        'transitions', cjson.encode(transitions),
        'updated_at', now,
        'updated_ts', now)
    return {1, "ok", pass_count, 0, 1}
end

return {1, "ok", pass_count, 0, 0}
"""

def get_shared_agenda(pair_slug: str) -> List[Dict[str, Any]]:
    r = _get_redis()
    key = f"npc_pair:{pair_slug}:agenda"
    items = r.zrange(key, 0, -1)
    result = []
    for agenda_id in items:
        item = get_agenda_item(pair_slug, agenda_id)
        if item:
            result.append(item)
    return result


def get_agenda_item(pair_slug: str, agenda_id: str) -> Optional[Dict[str, Any]]:
    r = _get_redis()
    key = f"npc_pair:{pair_slug}:agenda:{agenda_id}"
    data = r.hgetall(key)
    if not data:
        return None
    for field in ["evidence", "open_questions", "participating_npcs",
                  "delegations", "handoffs", "decisions"]:
        if field in data and data[field]:
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                data[field] = []
    return data


def create_agenda_item(
    pair_slug: str,
    agenda_key: str,
    objective: str,
    proposer: str,
    assigned_councilor: str = "",
    participating_npcs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new agenda item with caller-supplied stable agenda_key.
    Deduplicates by pair_slug + agenda_key. Returns existing item if found.
    """
    if not AGENDA_KEY_PATTERN.match(agenda_key):
        return {"_error": "invalid_agenda_key_format"}

    agenda_id = _stable_agenda_id(pair_slug, agenda_key)
    existing = get_agenda_item(pair_slug, agenda_id)
    if existing:
        return existing

    r = _get_redis()
    now = _now_ts()
    now_iso = _now_iso()

    item = {
        "id": agenda_id,
        "agenda_key": agenda_key,
        "objective": objective,
        "proposer": proposer,
        "status": "proposed",
        "assigned_councilor": assigned_councilor,
        "owner": "",
        "owner_version": "0",
        "owner_claimed_at": "",
        "participating_npcs": json.dumps(participating_npcs or []),
        "evidence": json.dumps([]),
        "open_questions": json.dumps([]),
        "next_action": "",
        "blocker": "",
        "handoffs": json.dumps([]),
        "decisions": json.dumps([]),
        "delegations": json.dumps([]),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_ts": now,
        "updated_ts": now,
    }

    r.hset(f"npc_pair:{pair_slug}:agenda:{agenda_id}", mapping=item)
    r.zadd(f"npc_pair:{pair_slug}:agenda", {agenda_id: now})
    logger.info("Created agenda item %s for pair %s", agenda_id, pair_slug)
    return get_agenda_item(pair_slug, agenda_id)


def update_agenda_item(
    pair_slug: str,
    agenda_id: str,
    **updates,
) -> Optional[Dict[str, Any]]:
    r = _get_redis()
    key = f"npc_pair:{pair_slug}:agenda:{agenda_id}"
    existing = r.hgetall(key)
    if not existing:
        return None
    if "status" in updates:
        if updates["status"] not in AGENDA_ITEM_STATUSES:
            return None
    updates["updated_at"] = _now_iso()
    updates["updated_ts"] = _now_ts()
    for field in ["evidence", "open_questions", "participating_npcs",
                  "delegations", "handoffs", "decisions"]:
        if field in updates and isinstance(updates[field], list):
            updates[field] = json.dumps(updates[field])
    r.hset(key, mapping=updates)
    return get_agenda_item(pair_slug, agenda_id)


# ── Atomic Ownership ───────────────────────────────────────────────

def claim_ownership(pair_slug: str, agenda_id: str, claimer: str) -> bool:
    """Atomically claim ownership of an agenda item.

    Lua is authoritative: returns 1 (claimed now), 2 (already owned by
    claimer — idempotent, no side effects), or 0 (missing/conflict).
    """
    r = _get_redis()
    key = f"npc_pair:{pair_slug}:agenda:{agenda_id}"
    result = r.eval(_CLAIM_LUA, 1, key, claimer, "", _now_iso())
    if result == 2:
        return True
    if result:
        update_agenda_item(pair_slug, agenda_id, status="investigating",
                           assigned_councilor=claimer, next_action="Claimed by " + claimer)
        _record_handoff(pair_slug, agenda_id, "", claimer, "claim")
    return bool(result)


def handoff_ownership(
    pair_slug: str,
    agenda_id: str,
    new_owner: str,
    expected_owner: str,
    expected_version: str = "",
) -> bool:
    """Atomically hand ownership from expected_owner to new_owner.

    Lua returns 0 if the item is missing, the current owner differs, or the
    expected_version mismatches — no bare hash is ever created by HSET.
    """
    r = _get_redis()
    key = f"npc_pair:{pair_slug}:agenda:{agenda_id}"
    result = r.eval(_HANDOFF_LUA, 1, key, new_owner, expected_owner, expected_version, _now_iso())
    if result:
        update_agenda_item(pair_slug, agenda_id, assigned_councilor=new_owner,
                           next_action="Handed to " + new_owner)
        _record_handoff(pair_slug, agenda_id, expected_owner, new_owner, "handoff")
    return bool(result)


def _record_handoff(pair_slug: str, agenda_id: str, from_owner: str, to_owner: str, handoff_type: str):
    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return
    handoffs = item.get("handoffs", [])
    if isinstance(handoffs, str):
        handoffs = json.loads(handoffs) if handoffs else []
    handoffs.append({
        "from": from_owner,
        "to": to_owner,
        "type": handoff_type,
        "timestamp": _now_iso(),
    })
    update_agenda_item(pair_slug, agenda_id, handoffs=handoffs)


def get_next_action_owner(pair_slug: str) -> Optional[str]:
    """Return the current owner of the oldest active agenda item, or None."""
    agenda = get_shared_agenda(pair_slug)
    active = [i for i in agenda if i["status"] not in {"completed", "rejected"}]
    if not active:
        return None
    active.sort(key=lambda x: x.get("created_ts", 0))
    return active[0].get("owner") or active[0].get("assigned_councilor") or None


# ── Delegation via Authoritative Messaging ─────────────────────────

def create_delegation(
    pair_slug: str,
    agenda_id: str,
    from_char_id: str,
    from_char_name: str,
    target_npc_id: str,
    question: str,
    reason: str,
    expected_format: str,
    deadline_hours: int = 24,
) -> Optional[Dict[str, Any]]:
    """Create a delegation through authoritative npc_messaging.send_message()."""
    if target_npc_id in PAIR_IDS:
        return None

    r = _get_redis()
    delegation_id = f"delegation_{uuid.uuid4().hex[:12]}"
    now = _now_ts()
    deadline = now + (deadline_hours * 3600)

    delegation = {
        "id": delegation_id,
        "agenda_id": agenda_id,
        "target_npc_id": target_npc_id,
        "question": question,
        "reason": reason,
        "expected_format": expected_format,
        "created_at": _now_iso(),
        "deadline": deadline,
        "status": "pending",
        "response": "",
        "response_ts": 0,
        "processed": False,
    }

    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return None

    delegations = item.get("delegations", [])
    if isinstance(delegations, str):
        delegations = json.loads(delegations) if delegations else []
    delegations.append(delegation)
    update_agenda_item(pair_slug, agenda_id, delegations=delegations, status="delegated")

    body = (
        f"Please investigate and respond to: {question}\n\n"
        f"Reason for selecting you: {reason}\n"
        f"Expected format: {expected_format}\n"
        f"Deadline: {deadline}\n"
        f"Agenda reference: {agenda_id}\n"
        f"Delegation ID: {delegation_id}\n"
        f"Callback: reply to this thread with your findings."
    )

    try:
        msg_result = _send_message(
            from_char_id=from_char_id,
            from_char_name=from_char_name,
            to_char_id=target_npc_id,
            subject=f"Delegation: {question[:80]}",
            body=body,
            thread_id=f"thread_delegation_{delegation_id}",
        )
        if msg_result:
            delegation["msg_id"] = msg_result.get("msg_id", "")
            delegation["thread_id"] = msg_result.get("thread_id", "")
            # Persist msg_id and thread_id back to Redis
            update_agenda_item(pair_slug, agenda_id, delegations=delegations)
    except Exception:
        logger.warning("_send_message failed for delegation %s", delegation_id)

    logger.info("Created delegation %s for agenda %s to NPC %s", delegation_id, agenda_id, target_npc_id)
    return delegation


def attach_delegation_response(
    pair_slug: str,
    agenda_id: str,
    delegation_id: str,
    response: str,
    msg_id: str = "",
    responder_id: str = "",
    thread_id: str = "",
) -> bool:
    """Attach a delegation response. Deduplicates by msg_id marker.

    The processed marker is written ONLY after all validation succeeds:
      - agenda item exists
      - delegation_id found in that agenda's delegations list
      - delegation not already processed
      - responder_id, when provided, matches delegation target_npc_id
      - thread_id, when provided, matches delegation thread_id
      - agenda_id matches the delegation's stored agenda_id
      - response successfully attached and persisted

    Malformed, unrelated, stale, or spoofed responses create no marker and
    no agenda mutation.
    """
    r = _get_redis()

    # Dedup check: if already processed, return False — but do NOT set marker
    if msg_id:
        processed_key = _delegation_processed_key(msg_id)
        if r.exists(processed_key):
            return False

    item = get_agenda_item(pair_slug, agenda_id)
    if not item:
        return False

    delegations = item.get("delegations", [])
    if isinstance(delegations, str):
        delegations = json.loads(delegations) if delegations else []

    deleg = None
    for d in delegations:
        if d.get("id") == delegation_id:
            deleg = d
            break

    if deleg is None:
        return False

    if deleg.get("processed"):
        return False

    # Validate agenda_id matches delegation's stored agenda_id
    if deleg.get("agenda_id", agenda_id) != agenda_id:
        return False

    # Validate responder matches the delegated NPC (when provided)
    if responder_id and deleg.get("target_npc_id", "") and responder_id != deleg["target_npc_id"]:
        return False

    # Validate thread_id matches (when provided)
    if thread_id and deleg.get("thread_id", "") and thread_id != deleg.get("thread_id", ""):
        return False

    # All validation passed — now mutate the delegation record
    deleg["status"] = "completed"
    deleg["response"] = response
    deleg["response_ts"] = _now_ts()
    deleg["processed"] = True

    update_agenda_item(pair_slug, agenda_id, delegations=delegations)

    # Marker written ONLY after successful persistence
    if msg_id:
        r.set(_delegation_processed_key(msg_id), "1")

    return True


def create_capability_request(
    pair_slug: str,
    agenda_id: str,
    requester_id: str,
    collaborating_councilor_id: str,
    capability_key: str,
    title: str,
    objective: str,
    blocker: str,
    attempts: str,
    consulted_npcs: List[str],
    evidence: str,
    requested_change: str,
    acceptance_criteria: str,
    expected_benefit: str,
    implementation_risks: str,
    priority: str = "medium",
) -> Dict[str, Any]:
    """Create a structured capability request with stable dedup identity."""
    r = _get_redis()
    stable_id = f"capreq_{uuid.uuid4().hex[:12]}"  # will be replaced by stable ID below
    # Actually use stable ID based on agenda + capability_key
    import hashlib
    content = f"{agenda_id}:{capability_key}"
    stable_id = f"capreq_{hashlib.sha256(content.encode()).hexdigest()[:16]}"

    # Check if request already exists (deduplication)
    existing_request_id = r.get(f"npc_capability_requests:stable:{stable_id}")
    if existing_request_id:
        existing = get_capability_request(existing_request_id)
        if existing:
            return existing

    request_id = f"capreq_{uuid.uuid4().hex[:12]}"
    now = _now_ts()
    now_iso = _now_iso()

    request = {
        "request_id": request_id,
        "stable_id": stable_id,
        "agenda_item_id": agenda_id,
        "pair_slug": pair_slug,
        "requester_id": requester_id,
        "collaborating_councilor_id": collaborating_councilor_id,
        "capability_key": capability_key,
        "title": title,
        "objective": objective,
        "blocker": blocker,
        "attempts": attempts,
        "consulted_npcs": json.dumps(consulted_npcs),
        "evidence": evidence,
        "requested_change": requested_change,
        "acceptance_criteria": acceptance_criteria,
        "expected_benefit": expected_benefit,
        "implementation_risks": implementation_risks,
        "priority": priority,
        "status": "draft",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_ts": now,
        "updated_ts": now,
        "transitions": json.dumps([]),
        "delivery_reference": "",
        "acceptance_test_result": "",
        "acceptance_test_evidence": "",
        "revision_number": "0",
    }

    r.hset(f"npc_capability_request:{request_id}", mapping=request)
    r.zadd("npc_capability_requests:index", {request_id: now})
    r.set(f"npc_capability_requests:stable:{stable_id}", request_id)
    logger.info("Created capability request %s for agenda %s", request_id, agenda_id)
    return request


def submit_capability_request(request_id: str, actor_id: str = "") -> bool:
    r = _get_redis()
    key = f"npc_capability_request:{request_id}"
    existing = r.hgetall(key)
    if not existing:
        return False
    for field in ["blocker", "acceptance_criteria", "objective", "requested_change"]:
        if not existing.get(field):
            return False
    transitions = json.loads(existing.get("transitions", "[]"))
    transitions.append({
        "from": "draft", "to": "submitted",
        "actor": actor_id or existing.get("requester_id", ""),
        "timestamp": _now_iso(), "reason": "",
    })
    r.hset(key, mapping={
        "status": "submitted",
        "transitions": json.dumps(transitions),
        "updated_at": _now_iso(), "updated_ts": _now_ts(),
    })
    return True


def get_capability_request(request_id: str) -> Optional[Dict[str, Any]]:
    r = _get_redis()
    data = r.hgetall(f"npc_capability_request:{request_id}")
    if not data:
        return None
    for field in ["consulted_npcs", "transitions"]:
        if field in data and data[field]:
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                data[field] = []
    return data


def get_capability_requests_for_agenda(agenda_id: str) -> List[Dict[str, Any]]:
    r = _get_redis()
    request_ids = r.zrange("npc_capability_requests:index", 0, -1)
    result = []
    for request_id in request_ids:
        request = get_capability_request(request_id)
        if request and request.get("agenda_item_id") == agenda_id:
            result.append(request)
    return result


def record_acceptance_test(
    request_id: str,
    councilor_id: str,
    result: str,
    evidence: str,
    expected_version: str = "",
) -> Dict[str, Any]:
    """Atomically record an acceptance test result for a capability request.

    Only councilors in PAIR_IDS may record. Each councilor gets a separate
    persisted acceptance record. Repeated identical recording is idempotent.
    Conflicting result replacement (e.g. pass → fail for same councilor) is
    rejected. When the second distinct PASS is recorded while status is
    delivered, the request atomically transitions to verification_pending.

    Returns: {"ok": bool, "idempotent": bool, "passed_count": int,
              "transitioned": bool, "error": Optional[str]}
    """
    if councilor_id not in PAIR_IDS:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False, "error": "only_councilors_may_record"}
    if result not in ACCEPTANCE_TEST_RESULTS:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False, "error": "invalid_result"}

    r = _get_redis()
    key = _capability_request_key(request_id)
    existing = r.hgetall(key)
    if not existing:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False, "error": "request_not_found"}

    current_status = existing.get("status", "")
    if current_status not in {"delivered", "verification_pending"}:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False,
                "error": "invalid_status_for_acceptance"}

    if expected_version and existing.get("lifecycle_version", "") != expected_version:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False,
                "error": "version_mismatch",
                "current_version": existing.get("lifecycle_version", "")}

    pair_slug = r.hget(key, "pair_slug") or ""
    if not pair_slug:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False, "error": "missing_pair_slug"}

    requester_id = r.hget(key, "requester_id") or ""
    collaborating_councilor_id = r.hget(key, "collaborating_councilor_id") or ""
    if not requester_id or not collaborating_councilor_id:
        return {"ok": False, "idempotent": False, "passed_count": 0,
                "transitioned": False, "error": "missing_pair_fields"}

    now_str = _now_iso()
    result_raw = r.eval(_ACCEPTANCE_TEST_LUA, 1, key,
                        request_id, councilor_id, result, evidence,
                        expected_version, pair_slug, now_str,
                        requester_id, collaborating_councilor_id)

    if isinstance(result_raw, (list, tuple)) and result_raw[0] == 1:
        passed_count = int(result_raw[2])
        is_idempotent = bool(result_raw[3]) if len(result_raw) > 3 else False
        transitioned = bool(result_raw[4]) if len(result_raw) > 4 else False

        if result in {"fail", "partial"} and not is_idempotent:
            _reopen_agenda_for_retest(existing, result)

        return {"ok": True, "idempotent": is_idempotent,
                "passed_count": passed_count, "transitioned": transitioned,
                "error": None}

    error_code = result_raw[1] if isinstance(result_raw, (list, tuple)) and len(result_raw) > 1 else "lua_failed"
    return {"ok": False, "idempotent": False, "passed_count": 0,
            "transitioned": False, "error": error_code}


def update_capability_request_status(
    request_id: str,
    status: str,
    actor_id: str = "",
    reason: str = "",
    delivery_reference: str = "",
    acceptance_test_result: str = "",
    acceptance_test_evidence: str = "",
) -> bool:
    """Update capability request status with full lifecycle enforcement.

    Authorization is validated in Python; the mutable update is performed
    atomically by _LIFECYCLE_TRANSITION_LUA against the current state.
    """
    if status not in CAPABILITY_REQUEST_STATUSES:
        return False

    r = _get_redis()
    key = f"npc_capability_request:{request_id}"
    existing = r.hgetall(key)
    if not existing:
        return False

    current_status = existing.get("status", "")
    allowed = CAPABILITY_REQUEST_TRANSITIONS.get(current_status, set())
    if status not in allowed:
        return False

    requester = existing.get("requester_id", "")
    collaborator = existing.get("collaborating_councilor_id", "")
    is_moderator = actor_id in {"moderator", "operator"}
    is_requester = actor_id == requester
    is_collaborator = actor_id == collaborator

    # ── Role-based authorization ──
    if status == "submitted" and not (actor_id in {"moderator", "operator", requester, collaborator}):
        return False
    if status in {"acknowledged", "approved", "rejected"} and not (actor_id in {"moderator", "operator"}):
        return False
    if status == "delivered" and not is_moderator:
        return False
    if status == "verification_pending" and not (is_requester or is_collaborator):
        return False
    if status == "verified":
        if not (actor_id in {"moderator", "operator"}):
            return False
        if acceptance_test_result not in ACCEPTANCE_TEST_RESULTS:
            return False
        # Pair acceptance: both councilors must have passed before verified
        pair_slug = r.hget(key, "pair_slug") or ""
        if pair_slug:
            acceptance_key = f"npc_pair:{pair_slug}:capability_acceptance:{request_id}"
            passed_members = r.scard(acceptance_key)
            if passed_members < 2:
                return False

    if status == "delivered" and not delivery_reference:
        return False
    if status == "verification_pending" and not acceptance_test_result:
        return False

    # ── Atomic lifecycle mutation ──
    actor_role = "moderator" if is_moderator else (
        "requester" if is_requester else (
            "collaborator" if is_collaborator else "councilor"
        )
    )
    now_str = _now_iso()
    result_raw = r.eval(_LIFECYCLE_TRANSITION_LUA, 1, key,
                        request_id, status, current_status,
                        existing.get("lifecycle_version", ""), actor_id, reason,
                        delivery_reference, acceptance_test_result,
                        acceptance_test_evidence, actor_role, now_str)

    if isinstance(result_raw, (list, tuple)) and result_raw[0] == 1:
        # ── Record pair acceptance for verification ──
        if status == "verification_pending" and acceptance_test_result == "pass" and actor_id in PAIR_IDS:
            pair_slug = r.hget(key, "pair_slug") or ""
            acceptance_key = f"npc_pair:{pair_slug}:capability_acceptance:{request_id}"
            r.sadd(acceptance_key, actor_id)

        if status == "delivered":
            _on_delivery(existing, delivery_reference)
        if status == "verification_pending" and acceptance_test_result in {"fail", "partial"}:
            _reopen_agenda_for_retest(existing, acceptance_test_result)
        return True
    return False


def _on_delivery(request_data: dict, delivery_reference: str):
    """Notify both councilors through existing messaging and reopen agenda."""
    pair_slug = request_data.get("pair_slug", "")
    agenda_id = request_data.get("agenda_item_id", "")
    requester = request_data.get("requester_id", "")
    collaborator = request_data.get("collaborating_councilor_id", "")
    title = request_data.get("title", "")

    try:
        for char_id, char_name in [(requester, "Councilor"), (collaborator, "Councilor")]:
            _send_pair_message(
                from_char_id="moderator",
                from_char_name="Sean / Federation Moderator",
                to_char_id=char_id,
                subject=f"Capability delivered: {title[:80]}",
                body=f"The capability '{title}' has been delivered.\n\n"
                     f"Delivery reference: {delivery_reference}\n"
                     f"Agenda: {agenda_id}\n"
                     f"Please test against acceptance criteria and record results.",
                thread_id=f"thread_delivery_{request_data.get('request_id', '')}",
            )
    except Exception:
        logger.warning("_send_pair_message failed for delivery notification")

    _reopen_agenda_for_retest(request_data, "delivered")


def _reopen_agenda_for_retest(request_data: dict, trigger: str):
    pair_slug = request_data.get("pair_slug", "")
    agenda_id = request_data.get("agenda_item_id", "")
    if not pair_slug or not agenda_id:
        return
    update_agenda_item(pair_slug, agenda_id,
                       status="requested",
                       next_action=f"Acceptance testing ({trigger})",
                       blocker="")


def get_all_capability_requests() -> List[Dict[str, Any]]:
    r = _get_redis()
    request_ids = r.zrange("npc_capability_requests:index", 0, -1)
    result = []
    for request_id in request_ids:
        request = get_capability_request(request_id)
        if request:
            result.append(request)
    return result


def get_agenda_summary(pair_slug: str) -> Dict[str, Any]:
    agenda = get_shared_agenda(pair_slug)
    active = [item for item in agenda if item["status"] not in {"completed", "rejected"}]
    return {
        "total_items": len(agenda),
        "active_items": len(active),
        "next_action_owner": get_next_action_owner(pair_slug),
        "items": agenda[:10],
    }


# ── Pre-decision hook for cognition cycle ──────────────────────────

def pre_decision_hook(pair_slug: str, char_id: str) -> Dict[str, Any]:
    """Deterministic pre-decision hook called before LLM action selection.

    Returns structured guidance:
    - If owned work exists: returns the agenda item and next action
    - If no owned work: returns empty guidance (LLM may propose new work)
    """
    agenda = get_shared_agenda(pair_slug)
    active = [i for i in agenda if i["status"] not in {"completed", "rejected"}]

    owned = [i for i in active if i.get("owner") == char_id]
    partner_work = [i for i in active if i.get("owner") and i.get("owner") != char_id]

    if owned:
        item = owned[0]
        return {
            "has_owned_work": True,
            "agenda_id": item["id"],
            "objective": item.get("objective", ""),
            "next_action": item.get("next_action", ""),
            "status": item.get("status", ""),
            "should_skip_proposal": True,
            "partner_work": [{"id": i["id"], "objective": i.get("objective", "")} for i in partner_work],
        }

    return {
        "has_owned_work": False,
        "should_skip_proposal": False,
        "partner_work": [{"id": i["id"], "objective": i.get("objective", "")} for i in partner_work],
    }