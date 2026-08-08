"""
Production capability-request producer bridge.

Bridges the NPC agent `request_capability` decision path to the
new work-loop publication actions (`capability_request_draft` /
`capability_request_submit`) without touching the legacy fallback.

Safe to deploy into the isolated worktree; does not modify the
live bind-mounted container files directly.
"""
import json
import logging
import os
import sys

logger = logging.getLogger("npc_work_loop_adapter")

# Ensure production shared package is discoverable whether mounted at
# /opt/federation_shared (live container) or present locally.
_SHARED_PATHS = [
    "/opt/federation_shared",
    "/docker/federation-game/shared",
]
for _sp in _SHARED_PATHS:
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)
    parent_sp = os.path.dirname(_sp)
    if parent_sp and parent_sp not in sys.path:
        sys.path.insert(0, parent_sp)

# ── Safe import of work-loop domain ───────────────────────────────────

_WORK_LOOP_OK = False
_execute_work_loop_action = None
PAIR_IDS = {"char_001", "char_306"}

try:
    from federation_work_loop.core import (
        execute_work_loop_action,
        get_shared_agenda,
        get_agenda_item,
        get_capability_request,
        get_areas,
        PAIR_IDS as _WL_PAIR_IDS,
        _pair_slug,
        _stable_capability_id,
    )
    _execute_work_loop_action = execute_work_loop_action
    PAIR_IDS = set(_WL_PAIR_IDS) if _WL_PAIR_IDS else PAIR_IDS
    _WORK_LOOP_OK = True
    logger.info("Work-loop import succeeded.")
except Exception as exc:
    logger.info("Work-loop import unavailable (%s). Legacy fallback path will be used when needed.", exc)
    _execute_work_loop_action = None
    _WORK_LOOP_OK = False


# ── Helper resolutions (match existing production helpers) ─────────────

def _resolve_pair_slug(actor_id: str, partner_id: str) -> str:
    return "__".join(sorted([actor_id, partner_id]))


def _get_partner_for(actor_id: str) -> str:
    if actor_id == "char_001":
        return "char_306"
    if actor_id == "char_306":
        return "char_001"
    others = sorted(PAIR_IDS - {actor_id})
    return others[0] if others else ""


def _resolve_active_agenda(pair_slug: str) -> dict:
    if not _WORK_LOOP_OK or not _execute_work_loop_action:
        return {}
    try:
        agenda = get_shared_agenda(pair_slug)
    except Exception:
        return {}
    for item in agenda:
        status = item.get("status", "")
        if status not in {"completed", "rejected"}:
            return item
    return {}


# ── Field mapping (in-world, no fourth-wall leakage) ───────────────────

def _map_request_fields(decision: dict, agenda_item: dict, actor_id: str, partner_id: str) -> dict:
    need_type = decision.get("need_type", "workflow_visibility")
    priority = decision.get("priority", "medium")
    description = decision.get("description", "")
    why_needed = decision.get("why_needed", "")
    suggested = decision.get("suggested_capability", "general_context_enrichment")

    agenda_id = agenda_item.get("id", "") if agenda_item else ""
    agenda_key = agenda_item.get("agenda_key", "") if agenda_item else ""

    objective_text = agenda_item.get("objective", "") if agenda_item else ""
    if not objective_text:
        objective_text = f"Address the observed gap: {need_type}"

    title_text = f"Capability request: {suggested}"
    blocker_text = description[:240] if description else f"Limited effectiveness due to missing {need_type}."
    attempts_text = f"Initial observation of repeated low-value turns due to missing {need_type}; seeking structured support through the pair agenda."
    consulted_npcs = [partner_id] if partner_id else []
    evidence_text = why_needed[:300] if why_needed else f"Repeated observations indicate a structural gap in {need_type}."
    requested_change_text = f"Provide the structured capability '{suggested}' to support pair-level work."
    acceptance_criteria_text = (
        f"The capability '{suggested}' is available to both councilors; "
        f"decisions referencing it produce measurable progress; no repeated need filings occur."
    )
    expected_benefit_text = f"Improved coordination on agenda '{agenda_key or agenda_id}' with reduced low-value turns."
    implementation_risks_text = "Requires shared agreement on scope; must not introduce fourth-wall artifacts."

    payload = {
        "actor_id": actor_id,
        "pair_slug": _resolve_pair_slug(actor_id, partner_id) if partner_id else _resolve_pair_slug(actor_id, "char_306"),
        "collaborating_councilor_id": partner_id,
        "agenda_id": agenda_id,
        "capability_key": suggested,
        "title": title_text,
        "objective": objective_text,
        "blocker": blocker_text,
        "attempts": attempts_text,
        "consulted_npcs": consulted_npcs,
        "evidence": evidence_text,
        "requested_change": requested_change_text,
        "acceptance_criteria": acceptance_criteria_text,
        "expected_benefit": expected_benefit_text,
        "implementation_risks": implementation_risks_text,
        "priority": priority,
    }
    return payload


# ── Public bridge: called by the production action handler ────────────

def handle_request_capability(
    decision: dict,
    actor_id: str,
    r,
    result: dict,
    desc: str = "",
    reasoning: str = "",
) -> bool:
    partner_id = _get_partner_for(actor_id)
    pair_slug = _resolve_pair_slug(actor_id, partner_id) if partner_id else ""

    if not _WORK_LOOP_OK or _execute_work_loop_action is None:
        logger.info("[%s] Work-loop unavailable; triggering legacy fallback.", actor_id)
        return False

    agenda_item = _resolve_active_agenda(pair_slug)
    if not agenda_item:
        logger.info("[%s] No valid active agenda for pair %s; triggering legacy fallback.", actor_id, pair_slug)
        return False

    payload = _map_request_fields(decision, agenda_item, actor_id, partner_id)
    agenda_id = payload.get("agenda_id", "")

    capability_key = payload.get("capability_key", "")
    if agenda_id and capability_key and _execute_work_loop_action:
        try:
            stable_id = _stable_capability_id(agenda_id, capability_key)
            existing_req_id = None
            import redis
            try:
                redis_client = redis.from_url(
                    os.environ.get("REDIS_TEST_URL",
                        os.environ.get("REDIS_URL", "redis://redis:6379/0")),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                existing_req_id = redis_client.get(f"npc_capability_requests:stable:{stable_id}")
            except Exception:
                pass
            if existing_req_id:
                # Equivalent request already exists. If it is still a draft
                # (e.g. a prior partial submit failure), the retry path must
                # submit the preserved draft rather than create a new one.
                existing_req = get_capability_request(existing_req_id) if get_capability_request else None
                if existing_req and existing_req.get("status") == "draft":
                    submit_payload = {
                        "actor_id": actor_id,
                        "pair_slug": pair_slug,
                        "request_id": existing_req_id,
                    }
                    submit_result = _execute_work_loop_action("capability_request_submit", submit_payload)
                    if submit_result.get("ok"):
                        final_req = submit_result.get("result", {})
                        result["action_taken"] = "capability_request_submitted"
                        result["request_id"] = existing_req_id
                        result["status"] = final_req.get("status", "submitted")
                        result["summary"] = f"Capability request submitted (retry): {existing_req_id} ({final_req.get('status', 'submitted')})"
                        logger.info("[%s] Retry submitted preserved draft: %s", actor_id, existing_req_id)
                        return True
                    else:
                        error = submit_result.get("error", "submit_failed")
                        result["action_taken"] = "capability_request_partial_failure"
                        result["request_id"] = existing_req_id
                        result["status"] = "draft_preserved_for_retry"
                        result["partial_error"] = error
                        result["summary"] = f"Draft preserved for retry: {existing_req_id} (submit error: {error})"
                        logger.info("[%s] Retry submit failed; draft preserved %s", actor_id, existing_req_id)
                        return False
                # Already submitted or beyond: return it idempotently.
                result["action_taken"] = "capability_request_existing"
                result["request_id"] = existing_req_id
                result["status"] = "existing"
                result["summary"] = f"Equivalent capability request already exists: {existing_req_id}"
                logger.info("[%s] Idempotent existing request returned: %s", actor_id, existing_req_id)
                return True
        except Exception as exc:
            logger.warning("[%s] Stable-id check failed: %s", actor_id, exc)

    try:
        draft_result = _execute_work_loop_action("capability_request_draft", payload)
        if not draft_result.get("ok"):
            error = draft_result.get("error", "draft_failed")
            logger.info("[%s] Draft failed (%s); triggering legacy fallback.", actor_id, error)
            return False
        request_obj = draft_result.get("result", {})
        request_id = request_obj.get("request_id", "")
        if not request_id:
            logger.info("[%s] Draft returned no request_id; triggering legacy fallback.", actor_id)
            return False
    except Exception as exc:
        logger.info("[%s] Draft raised exception (%s); triggering legacy fallback.", actor_id, exc)
        return False

    try:
        submit_payload = {
            "actor_id": actor_id,
            "pair_slug": pair_slug,
            "request_id": request_id,
        }
        submit_result = _execute_work_loop_action("capability_request_submit", submit_payload)
        if submit_result.get("ok"):
            final_req = submit_result.get("result", {})
            result["action_taken"] = "capability_request_submitted"
            result["request_id"] = request_id
            result["status"] = final_req.get("status", "submitted")
            result["summary"] = f"Capability request submitted: {request_id} ({final_req.get('status', 'submitted')})"
            logger.info("[%s] Capability request submitted: %s", actor_id, request_id)
            return True
        else:
            error = submit_result.get("error", "submit_failed")
            current_status = submit_result.get("current_status", "")
            if current_status == "draft" or error in ("submit_failed",):
                result["action_taken"] = "capability_request_partial_failure"
                result["request_id"] = request_id
                result["status"] = "draft_preserved_for_retry"
                result["partial_error"] = error
                result["summary"] = f"Draft preserved for retry: {request_id} (submit error: {error})"
                logger.info("[%s] Partial failure: draft preserved %s; retry path enabled.", actor_id, request_id)
                return False
            else:
                logger.info("[%s] Non-retryable submit failure (%s); triggering legacy fallback.", actor_id, error)
                return False
    except Exception as exc:
        logger.info("[%s] Submit raised exception (%s); triggering legacy fallback.", actor_id, exc)
        return False


# ── Area / world-expansion bridge ─────────────────────────────────────

def handle_found_area(decision: dict, actor_id: str, r, result: dict) -> bool:
    """Route a `create_area` decision to the durable work-loop `area_found`
    action so the pair can expand their world map persistently."""
    partner_id = _get_partner_for(actor_id)
    pair_slug = _resolve_pair_slug(actor_id, partner_id) if partner_id else ""

    if not _WORK_LOOP_OK or _execute_work_loop_action is None:
        logger.info("[%s] Work-loop unavailable; create_area cannot persist.", actor_id)
        return False

    payload = {
        "actor_id": actor_id,
        "pair_slug": pair_slug,
        "area_id": decision.get("area_id", ""),
        "name": decision.get("name", ""),
        "description": decision.get("description", ""),
        "x": decision.get("x", 0),
        "y": decision.get("y", 0),
        "region_type": decision.get("region_type", "frontier"),
        "resource_profile": decision.get("resource_profile", "mixed"),
        "danger_level": decision.get("danger_level", 5),
        "adjacent_sector_ids": decision.get("adjacent_sector_ids", []),
    }
    try:
        res = _execute_work_loop_action("area_found", payload)
    except Exception as e:
        logger.error("[%s] area_found raised: %s", actor_id, e)
        return False

    if res.get("ok"):
        result["action_taken"] = "area_found"
        result["area_id"] = (res.get("result") or {}).get("area_id")
        result["status"] = "found" if not res.get("idempotent") else "existing"
        result["summary"] = f"Found area '{payload.get('name')}' ({result['status']})"
        return True

    result["action_taken"] = "area_found_failed"
    result["partial_error"] = res.get("error")
    result["summary"] = f"Area foundation failed: {res.get('error')}"
    return False


def current_areas_summary() -> str:
    """Human-readable list of areas already on the pair's shared map, for
    injection into the decision prompt so create_area proposes new areas."""
    if not _WORK_LOOP_OK:
        return ""
    try:
        pair_slug = "__".join(sorted(PAIR_IDS))
        areas = get_areas(pair_slug)
    except Exception:
        return ""
    if not areas:
        return ""
    return "; ".join(
        f"{a.get('area_id', '?')} ({a.get('name', '?')}, founded_by={a.get('founded_by', '?')})"
        for a in areas
    )


def area_exists_on_map(area_id: str) -> bool:
    """Deterministic check: is this area_id already on the pair's shared map?"""
    if not _WORK_LOOP_OK or not area_id:
        return False
    try:
        from federation_work_loop.core import get_area
        pair_slug = "__".join(sorted(PAIR_IDS))
        return get_area(pair_slug, area_id) is not None
    except Exception:
        return False
