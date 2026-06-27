"""Institution and role state for the first organizational Federation slice."""

import json
from datetime import datetime, timezone

INSTITUTION_INDEX_KEY = "institution:index"
ROLE_INDEX_KEY = "role:index"
ACTIVE_WORKFLOWS_KEY = "workflow:active"
COMPLETED_WORKFLOWS_KEY = "workflow:completed"

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
    "submitted": "under_review",
    "under_review": "deliberating",
    "deliberating": "ratified",
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


def ensure_proposal_review_workflow(r, councilor_id, artifact, role_ctx, now=None):
    """Create one proposal_review workflow per source artifact id."""
    timestamp = _now_iso(now)
    artifact_id = artifact["artifact_id"]
    workflow_lookup_key = f"workflow:source_artifact:{artifact_id}"
    existing = r.get(workflow_lookup_key)
    if existing:
        return existing

    workflow_id = f"workflow:proposal_review:{artifact_id}"
    workflow_record = {
        "type": "proposal_review",
        "institution_id": role_ctx["institution_id"],
        "role_id": role_ctx["role_id"],
        "source_artifact_id": artifact_id,
        "source_councilor_id": councilor_id,
        "artifact_kind": "proposal",
        "status": "submitted",
        "created_at": timestamp,
        "updated_at": timestamp,
        "title": artifact.get("title", "Untitled Proposal"),
    }
    r.hset(workflow_id, mapping=workflow_record)
    r.sadd("workflow:index", workflow_id)
    r.sadd(ACTIVE_WORKFLOWS_KEY, workflow_id)
    r.set(workflow_lookup_key, workflow_id)
    _append_workflow_event(r, workflow_id, timestamp, "submitted", "Proposal entered institutional review.")
    return workflow_id


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

    if artifact["artifact_kind"] == "proposal":
        artifact["workflow_id"] = ensure_proposal_review_workflow(
            r, councilor_id, artifact, role_ctx, now=now
        )

    return artifact


def run_institution_tick(r, now=None):
    """Advance active institution workflows one step per tick."""
    seed_result = seed_institutions(r, now=now)
    timestamp = _now_iso(now)
    workflows_advanced = 0

    for workflow_id in sorted(r.smembers(ACTIVE_WORKFLOWS_KEY)):
        record = r.hgetall(workflow_id)
        current_status = record.get("status")
        next_status = WORKFLOW_TRANSITIONS.get(current_status)
        if not next_status:
            continue
        r.hset(workflow_id, mapping={"status": next_status, "updated_at": timestamp})
        _append_workflow_event(
            r,
            workflow_id,
            timestamp,
            next_status,
            f"Workflow advanced from {current_status} to {next_status}.",
        )
        workflows_advanced += 1
        if next_status == "ratified":
            r.srem(ACTIVE_WORKFLOWS_KEY, workflow_id)
            r.sadd(COMPLETED_WORKFLOWS_KEY, workflow_id)

    return {
        **seed_result,
        "workflows_advanced": workflows_advanced,
        "active_workflows": len(r.smembers(ACTIVE_WORKFLOWS_KEY)),
        "completed_workflows": len(r.smembers(COMPLETED_WORKFLOWS_KEY)),
    }
