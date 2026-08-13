"""Institution and role state for the first organizational Federation slice."""

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("institutions")

INSTITUTION_INDEX_KEY = "institution:index"
ROLE_INDEX_KEY = "role:index"
ACTIVE_WORKFLOWS_KEY = "workflow:active"
COMPLETED_WORKFLOWS_KEY = "workflow:completed"
WORKFLOW_INDEX_KEY = "workflow:index"

NPC_OUTCOME_HISTORY_KEY = "npc:{npc_id}:workflow_outcomes"
NPC_RECENT_OUTCOMES_KEY = "npc:{npc_id}:recent_outcomes"
MAX_RECENT_OUTCOMES = 20

INSTITUTION_SEEDS = {
    "institution:research_division_council": {
        "name": "Research Division Council",
        "kind": "research_body",
        "mandate": "Evaluate proposals that affect discovery, archives, and scientific direction.",
        "status": "active",
    },
    "institution:consciousness_collective_council": {
        "name": "Consciousness Collective Council",
        "kind": "council",
        "mandate": "Review proposals involving cognition, anomaly response, and long-range foresight.",
        "status": "active",
    },
}

ROLE_SEEDS = {
    "role:research_chief_mathematician": {
        "institution_id": "institution:research_division_council",
        "title": "Chief Mathematician",
        "scope": "Research charters, sector accords, and analytical proposals.",
        "authority": "review_and_propose",
        "holder_char_id": "char_001",
        "status": "active",
    },
    "role:collective_oracle": {
        "institution_id": "institution:consciousness_collective_council",
        "title": "Collective Oracle",
        "scope": "Anomaly response, institutional foresight, and consensus warnings.",
        "authority": "review_and_warn",
        "holder_char_id": "char_306",
        "status": "active",
    },
}

WORKFLOW_TRANSITIONS = {
    "proposal_review": {
        "submitted": "under_review",
        "under_review": "deliberating",
        "deliberating": "ratified",
    },
    "analysis_review": {
        "submitted": "peer_review",
        "peer_review": "endorsed",
    },
}

TERMINAL_STATES = frozenset({"ratified", "endorsed", "approved", "rejected"})

VALID_WORKFLOW_TYPES = set(WORKFLOW_TRANSITIONS)

WORKFLOW_DEFAULTS = {
    "proposal_review": {"artifact_kind": "proposal", "label": "Proposal"},
    "analysis_review": {"artifact_kind": "analysis", "label": "Analysis"},
}


def _now_iso(now=None):
    if now:
        return now
    return datetime.now(timezone.utc).isoformat()


def seed_institutions(r, now=None):
    """Ensure the initial institution and role topology exists."""
    timestamp = _now_iso(now)
    institutions_seeded = 0
    roles_seeded = 0

    for institution_id, payload in INSTITUTION_SEEDS.items():
        institutions_seeded += r.sadd(INSTITUTION_INDEX_KEY, institution_id)
        record = dict(payload)
        record["created_at"] = timestamp
        r.hset(institution_id, mapping=record)

    for role_id, payload in ROLE_SEEDS.items():
        roles_seeded += r.sadd(ROLE_INDEX_KEY, role_id)
        record = dict(payload)
        record["created_at"] = timestamp
        r.hset(role_id, mapping=record)
        institution_id = payload["institution_id"]
        holder_char_id = payload["holder_char_id"]
        r.sadd(f"{institution_id}:roles", role_id)
        r.sadd(f"{institution_id}:members", holder_char_id)
        r.set(f"councilor:{holder_char_id}:role", role_id)
        r.set(f"councilor:{holder_char_id}:institution", institution_id)

    return {
        "institutions_seeded": institutions_seeded,
        "roles_seeded": roles_seeded,
    }


def get_councilor_role_context(r, councilor_id):
    """Return the institution and role held by a councilor NPC."""
    seed_institutions(r)
    role_id = r.get(f"councilor:{councilor_id}:role")
    institution_id = r.get(f"councilor:{councilor_id}:institution")
    if not role_id or not institution_id:
        return None
    role = r.hgetall(role_id)
    institution = r.hgetall(institution_id)
    return {
        "councilor_id": councilor_id,
        "role_id": role_id,
        "role_title": role.get("title", ""),
        "institution_id": institution_id,
        "institution_name": institution.get("name", ""),
    }


def classify_artifact_kind(artifact):
    """Classify an artifact into the first institution-facing kinds."""
    raw = " ".join(
        str(artifact.get(part, ""))
        for part in ("category", "title", "body", "content", "description")
    ).lower()
    if any(term in raw for term in ("proposal", "propose", "charter", "accord", "compact", "law", "proclamation")):
        return "proposal"
    if any(term in raw for term in ("analysis", "report", "diagnostic", "brief", "forecast")):
        return "analysis"
    return "councilor_note"


def _append_workflow_event(r, workflow_id, now, status, detail):
    r.rpush(
        f"{workflow_id}:events",
        json.dumps(
            {
                "timestamp": now,
                "status": status,
                "detail": detail,
            }
        ),
    )


def _decrement_inst_counter(r, institution_id, counter_key):
    key = f"{institution_id}:{counter_key}"
    try:
        val = int(r.get(key) or 0)
        if val > 0:
            r.set(key, str(val - 1))
    except (ValueError, TypeError):
        pass


def _increment_inst_counter(r, institution_id, counter_key):
    key = f"{institution_id}:{counter_key}"
    try:
        val = int(r.get(key) or 0)
        r.set(key, str(val + 1))
    except (ValueError, TypeError):
        pass


def _rebuild_inst_counters(r):
    """Rebuild per-institution workflow counters from scratch."""
    for inst_id in r.smembers(INSTITUTION_INDEX_KEY):
        active_count = 0
        completed_count = 0
        for wf_id in r.smembers(ACTIVE_WORKFLOWS_KEY):
            rec = r.hgetall(wf_id)
            if rec.get("institution_id") == inst_id:
                active_count += 1
        for wf_id in r.smembers(COMPLETED_WORKFLOWS_KEY):
            rec = r.hgetall(wf_id)
            if rec.get("institution_id") == inst_id:
                completed_count += 1
        r.set(f"{inst_id}:active_workflows", str(active_count))
        r.set(f"{inst_id}:completed_workflows", str(completed_count))


# ---------------------------------------------------------------------------
# Title-based workflow dedup — mirrors backend/institutions.py
# NPC-authored workflow titles are free-form LLM text that frequently re-emits
# the same proposal/sector under lightly different casing or punctuation.
# Because ensure_workflow keys per-source-artifact by uuid (and every NPC
# artifact carries a fresh uuid), identical conceptual proposals mint brand-new
# workflows every time, which is the root cause of the 600+ role/workflow bloat
# seen in metrics. Normalizing a single concept to one canonical key lets us
# anchor repeat emits to the already-created workflow instead of minting more.
# ---------------------------------------------------------------------------

TITLE_DEDUPE_TTL_SEC = max(
    int(os.environ.get("WORKFLOW_TITLE_DEDUPE_TTL_DAYS", "30")) * 86400, 86400
)


def _normalize_workflow_title(raw_title, wf_type):
    """Return a stable, case/whitespace-normalized title for dedup purposes."""
    if raw_title is None:
        return (wf_type or "untitled").lower()
    text = " ".join(str(raw_title).lower().split())
    # Collapse leading templated base-phrases NPCs prefix onto proposals
    for prefix in ("proposal:", "analysis:", "for review:", "review:", "action:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    id_text = text or (wf_type or "untitled")
    # Drop trailing category/byline fragments so "X (Research Division Council)"
    # collapses onto "X" too.
    if " (" in id_text:
        id_text = id_text.split(" (", 1)[0].strip()
    return id_text or (wf_type or "untitled")


def ensure_workflow(r, councilor_id, artifact, role_ctx, wf_type, now=None):
    """Create one workflow of the given type per source artifact id.

    Returns the workflow_id (existing or newly created).

    Dedup chain:
      1. Same source artifact uuid → existing workflow (original behavior).
      2. Same normalized title (same wf_type + councilor_id) within TTL →
         the already-anchored workflow for that concept (prevents bloat from
         repeat LLM emits with fresh uuids but identical conceptual title).
    """
    if wf_type not in VALID_WORKFLOW_TYPES:
        raise ValueError(f"Unknown workflow type: {wf_type!r}")

    timestamp = _now_iso(now)
    artifact_id = artifact["artifact_id"]
    workflow_lookup_key = f"workflow:source_artifact:{artifact_id}"
    existing = r.get(workflow_lookup_key)
    if existing:
        return existing

    # Near-duplicate collapse: if a workflow for the SAME normalized concept
    # title already exists (and is still within its dedup window), anchor to it
    # instead of minting a new workflow per fresh artifact uuid.
    title_lookup_key = "workflow:title:{}:{}:{}".format(
        wf_type,
        councilor_id,
        _normalize_workflow_title(artifact.get("title"), wf_type),
    )
    anchored = r.get(title_lookup_key)
    if anchored:
        r.set(workflow_lookup_key, anchored)
        return anchored

    defaults = WORKFLOW_DEFAULTS.get(wf_type, {"artifact_kind": wf_type, "label": wf_type})
    workflow_id = f"workflow:{wf_type}:{artifact_id}"
    # Atomically claim the canonical title anchor BEFORE creating the workflow
    # record. SET NX EX is the single source of truth for "which workflow owns
    # this normalized title". If another reconciler won the race, reuse its
    # workflow instead of minting a duplicate.
    won_anchor = r.set(
        title_lookup_key,
        workflow_id,
        nx=True,
        ex=TITLE_DEDUPE_TTL_SEC,
    )
    if not won_anchor:
        winner = r.get(title_lookup_key) or workflow_id
        r.set(workflow_lookup_key, winner)
        return winner

    workflow_record = {
        "type": wf_type,
        "institution_id": role_ctx["institution_id"],
        "role_id": role_ctx["role_id"],
        "source_artifact_id": artifact_id,
        "source_councilor_id": councilor_id,
        "artifact_kind": defaults["artifact_kind"],
        "status": "submitted",
        "created_at": timestamp,
        "updated_at": timestamp,
        "title": artifact.get("title", f"Untitled {defaults['label']}"),
    }
    r.hset(workflow_id, mapping=workflow_record)
    r.sadd(WORKFLOW_INDEX_KEY, workflow_id)
    r.sadd(ACTIVE_WORKFLOWS_KEY, workflow_id)
    r.set(workflow_lookup_key, workflow_id)
    _append_workflow_event(
        r, workflow_id, timestamp, "submitted",
        f"{defaults['label']} entered institutional review.",
    )
    _increment_inst_counter(r, role_ctx["institution_id"], "active_workflows")
    return workflow_id


def ensure_proposal_review_workflow(r, councilor_id, artifact, role_ctx, now=None):
    """Create one proposal_review workflow per source artifact id."""
    return ensure_workflow(r, councilor_id, artifact, role_ctx, "proposal_review", now=now)


def ensure_analysis_review_workflow(r, councilor_id, artifact, role_ctx, now=None):
    """Create one analysis_review workflow per source artifact id."""
    return ensure_workflow(r, councilor_id, artifact, role_ctx, "analysis_review", now=now)


def annotate_artifact(r, councilor_id, artifact, now=None):
    """Attach institution metadata to a councilor artifact."""
    seed_institutions(r, now=now)
    role_ctx = get_councilor_role_context(r, councilor_id)
    if not role_ctx:
        artifact.setdefault("institution_id", "")
        artifact.setdefault("role_id", "")
        artifact.setdefault("workflow_id", "")
        artifact.setdefault("artifact_kind", "councilor_note")
        return artifact

    artifact["institution_id"] = role_ctx["institution_id"]
    artifact["role_id"] = role_ctx["role_id"]
    artifact["artifact_kind"] = classify_artifact_kind(artifact)
    artifact["workflow_id"] = ""

    kind_to_type = {"proposal": "proposal_review", "analysis": "analysis_review"}
    wf_type = kind_to_type.get(artifact["artifact_kind"])
    if wf_type:
        artifact["workflow_id"] = ensure_workflow(
            r, councilor_id, artifact, role_ctx, wf_type, now=now
        )

    return artifact


def advance_workflow(r, workflow_id, now=None):
    """Advance a single workflow one step. Returns (advanced: bool, new_status: str)."""
    timestamp = _now_iso(now)
    record = r.hgetall(workflow_id)
    if not record:
        return False, ""

    wf_type = record.get("type", "")
    if wf_type not in WORKFLOW_TRANSITIONS:
        log.warning("Skipping workflow %s with unknown type %s", workflow_id, wf_type)
        return False, ""

    transitions = WORKFLOW_TRANSITIONS[wf_type]
    current_status = record.get("status")
    next_status = transitions.get(current_status)
    if not next_status:
        return False, current_status

    institution_id = record.get("institution_id", "")

    r.hset(workflow_id, mapping={"status": next_status, "updated_at": timestamp})
    _append_workflow_event(
        r,
        workflow_id,
        timestamp,
        next_status,
        f"Workflow advanced from {current_status} to {next_status}.",
    )

    if next_status in TERMINAL_STATES:
        r.srem(ACTIVE_WORKFLOWS_KEY, workflow_id)
        r.sadd(COMPLETED_WORKFLOWS_KEY, workflow_id)
        _decrement_inst_counter(r, institution_id, "active_workflows")
        _increment_inst_counter(r, institution_id, "completed_workflows")
        _record_outcome(r, workflow_id, record, next_status)

    return True, next_status


def override_workflow_status(r, workflow_id, new_status, now=None):
    """Override a workflow to an arbitrary status. Used for manual intervention."""
    timestamp = _now_iso(now)
    record = r.hgetall(workflow_id)
    if not record:
        return False

    old_status = record.get("status")
    institution_id = record.get("institution_id", "")

    r.hset(workflow_id, mapping={"status": new_status, "updated_at": timestamp})
    _append_workflow_event(
        r,
        workflow_id,
        timestamp,
        new_status,
        f"Status overridden from {old_status} to {new_status} (manual).",
    )

    was_active = workflow_id in r.smembers(ACTIVE_WORKFLOWS_KEY)
    is_terminal = new_status in TERMINAL_STATES

    if is_terminal and was_active:
        r.srem(ACTIVE_WORKFLOWS_KEY, workflow_id)
        r.sadd(COMPLETED_WORKFLOWS_KEY, workflow_id)
        _decrement_inst_counter(r, institution_id, "active_workflows")
        _increment_inst_counter(r, institution_id, "completed_workflows")
        _record_outcome(r, workflow_id, record, new_status)
    elif not is_terminal and not was_active:
        r.srem(COMPLETED_WORKFLOWS_KEY, workflow_id)
        r.sadd(ACTIVE_WORKFLOWS_KEY, workflow_id)
        _decrement_inst_counter(r, institution_id, "completed_workflows")
        _increment_inst_counter(r, institution_id, "active_workflows")

    return True


def set_institution_status(r, institution_id, new_status, now=None):
    """Change an institution's status (e.g. active → suspended)."""
    rec = r.hgetall(institution_id)
    if not rec:
        return False
    timestamp = _now_iso(now)
    r.hset(institution_id, mapping={"status": new_status})
    return True


def run_institution_tick(r, now=None):
    """Advance active institution workflows one step per tick."""
    seed_result = seed_institutions(r, now=now)
    timestamp = _now_iso(now)
    workflows_advanced = 0

    active_ids = sorted(r.smembers(ACTIVE_WORKFLOWS_KEY))
    for workflow_id in active_ids:
        advanced, _ = advance_workflow(r, workflow_id, now=timestamp)
        if advanced:
            workflows_advanced += 1

    return {
        **seed_result,
        "workflows_advanced": workflows_advanced,
        "active_workflows": len(r.smembers(ACTIVE_WORKFLOWS_KEY)),
        "completed_workflows": len(r.smembers(COMPLETED_WORKFLOWS_KEY)),
    }


def _record_outcome(r, workflow_id, record, new_status):
    if new_status not in TERMINAL_STATES:
        return
    source_npc = record.get("source_councilor_id", "")
    if not source_npc:
        return
    wf_type = record.get("type", "")
    outcome = "approved" if new_status in ("ratified", "endorsed", "approved") else "rejected"
    hist_key = NPC_OUTCOME_HISTORY_KEY.format(npc_id=source_npc)
    r.hincrby(hist_key, outcome, 1)
    recent_key = NPC_RECENT_OUTCOMES_KEY.format(npc_id=source_npc)
    entry = json.dumps({"workflow_id": workflow_id, "type": wf_type, "outcome": outcome, "ts": _now_iso()})
    r.lpush(recent_key, entry)
    r.ltrim(recent_key, 0, MAX_RECENT_OUTCOMES - 1)


def get_npc_outcome_history(r, npc_id):
    hist_key = NPC_OUTCOME_HISTORY_KEY.format(npc_id=npc_id)
    raw = r.hgetall(hist_key)
    approved = int(raw.get("approved", 0))
    rejected = int(raw.get("rejected", 0))
    total = approved + rejected
    recent_key = NPC_RECENT_OUTCOMES_KEY.format(npc_id=npc_id)
    recent_raw = r.lrange(recent_key, 0, -1)
    recent = []
    for item in recent_raw:
        try:
            recent.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            pass
    consecutive_rejections = 0
    for entry in recent:
        if entry.get("outcome") == "rejected":
            consecutive_rejections += 1
        else:
            break
    recent_rejected_types = set(
        e.get("type", "") for e in recent[:5] if e.get("outcome") == "rejected"
    )
    return {
        "approved": approved,
        "rejected": rejected,
        "total": total,
        "consecutive_rejections": consecutive_rejections,
        "recent_rejected_types": recent_rejected_types,
        "recent": recent[:10],
    }
