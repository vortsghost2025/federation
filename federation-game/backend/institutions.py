"""Institution and role state for the first organizational Federation slice."""

import json
import logging
import os
import redis
from datetime import datetime, timezone

log = logging.getLogger("institutions")

INSTITUTION_INDEX_KEY = "institution:index"
ROLE_INDEX_KEY = "role:index"
ACTIVE_WORKFLOWS_KEY = "workflow:active"
COMPLETED_WORKFLOWS_KEY = "workflow:completed"
WORKFLOW_INDEX_KEY = "workflow:index"
EFFECTS_PENDING_KEY = "workflow:effects_pending"
BACKFILL_MARKER_KEY = "migration:effects_pending_backfill:v1"

NPC_OUTCOME_HISTORY_KEY = "npc:{npc_id}:workflow_outcomes"
NPC_RECENT_OUTCOMES_KEY = "npc:{npc_id}:recent_outcomes"
MAX_RECENT_OUTCOMES = 20

# Completed workflows keep their per-workflow detail hash for this long, then
# the hash self-expires so completed institutional history does not accumulate
# forever in Redis. The completed-ID set is small (id-only); the heavy detail
# is what this bounds. Env-overridable.
WORKFLOW_ARCHIVE_TTL_DAYS = int(os.environ.get("WORKFLOW_ARCHIVE_TTL_DAYS", "30"))

# ── Phase 1A.2: Atomic Consequence Commit ───────────────────
# Only workflows created at or after this UTC timestamp produce outcome effects.
# Protects against backlog dumps of pre-existing workflows.
# Format: ISO 8601 string; None disables the fence.
EFFECTS_CUTOFF_TIMESTAMP = os.environ.get("FEDERATION_EFFECTS_CUTOFF", "2026-08-02T03:16:07+00:00")

# Per-execution-cycle aggregate caps on institutional world-state deltas.
# Prevents runaway state jumps when many workflows complete in one batch.
# Applied atomically via Lua script — no race conditions.
EFFECTS_CAPS = {
    "morale": 5.0,
    "stability": 5.0,
    "resource_abundance": 4.0,
    "anomaly_activity": 3.0,
    "threat_level": 3.0,
    "tension_level": 3.0,
}

# Redis keys for Phase 1A.2 atomicity
EFFECT_APPLIED_KEY = "workflow:effect_applied:{workflow_id}"
EFFECT_RECEIPT_KEY = "workflow:effect_receipt:{workflow_id}"

# TTL for execution-cycle cap tracking (7 days — enough for replay analysis)
CAP_HASH_TTL_SEC = 604800

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


def _now_epoch(now=None):
    """Return current UTC epoch as float, or parse *now* if it's a timestamp string."""
    if now is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(now, str):
        try:
            return float(now)
        except (ValueError, TypeError):
            try:
                return datetime.fromisoformat(now).timestamp()
            except (ValueError, TypeError):
                return datetime.now(timezone.utc).timestamp()
    if isinstance(now, datetime):
        return now.timestamp()
    return now


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


def ensure_workflow(r, councilor_id, artifact, role_ctx, wf_type, now=None):
    """Create one workflow of the given type per source artifact id.

    Returns the workflow_id (existing or newly created).
    """
    if wf_type not in VALID_WORKFLOW_TYPES:
        raise ValueError(f"Unknown workflow type: {wf_type!r}")

    timestamp = _now_iso(now)
    artifact_id = artifact["artifact_id"]
    workflow_lookup_key = f"workflow:source_artifact:{artifact_id}"
    existing = r.get(workflow_lookup_key)
    if existing:
        return existing

    defaults = WORKFLOW_DEFAULTS.get(wf_type, {"artifact_kind": wf_type, "label": wf_type})
    workflow_id = f"workflow:{wf_type}:{artifact_id}"
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


def advance_workflow(r, workflow_id, now=None, execution_cycle_id=""):
    """Advance a single workflow one step. Returns (advanced: bool, new_status: str).

    When the workflow reaches a terminal state, calls _record_outcome with
    the execution_cycle_id for atomic consequence commit (Phase 1A.2).
    """
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
        _record_outcome(r, workflow_id, record, next_status, execution_cycle_id)
        # Archive: expire the per-workflow detail hash so completed history
        # does not accumulate unbounded. The id-only completed set stays small.
        try:
            r.expire(workflow_id, WORKFLOW_ARCHIVE_TTL_DAYS * 86400)
        except Exception:
            pass

    return True, next_status


def override_workflow_status(r, workflow_id, new_status, now=None, execution_cycle_id=""):
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
        _record_outcome(r, workflow_id, record, new_status, execution_cycle_id)
        # Archive: bound the completed workflow detail hash (see advance_workflow).
        try:
            r.expire(workflow_id, WORKFLOW_ARCHIVE_TTL_DAYS * 86400)
        except Exception:
            pass
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


def run_institution_tick(r, now=None, execution_cycle_id=None):
    """Advance active institution workflows one step per tick.

    Generates an execution_cycle_id if not provided. This ID is threaded
    through to _apply_outcome_effects() for per-cycle aggregate cap tracking
    (Phase 1A.2).
    """
    seed_result = seed_institutions(r, now=now)
    timestamp = _now_iso(now)

    # Generate execution cycle ID if not provided
    # Use UUID to guarantee uniqueness even within the same second
    if execution_cycle_id is None:
        import uuid
        execution_cycle_id = str(uuid.uuid4())[:12]

    # ── Reconcile pending effects from prior crashes before advancing workflows ──
    # Uses a separate execution-cycle bucket so recovered effects don't consume
    # the current tick's cap budget.
    reconciliation = reconcile_pending_effects(
        r,
        execution_cycle_id=f"reconcile_{execution_cycle_id}",
    )

    workflows_advanced = 0

    active_ids = sorted(r.smembers(ACTIVE_WORKFLOWS_KEY))
    for workflow_id in active_ids:
        advanced, _ = advance_workflow(r, workflow_id, now=timestamp, execution_cycle_id=execution_cycle_id)
        if advanced:
            workflows_advanced += 1

    return {
        **seed_result,
        "workflows_advanced": workflows_advanced,
        "active_workflows": len(r.smembers(ACTIVE_WORKFLOWS_KEY)),
        "completed_workflows": len(r.smembers(COMPLETED_WORKFLOWS_KEY)),
        "execution_cycle_id": execution_cycle_id,
        "reconciliation": reconciliation,
    }


# ── Phase 1A.2: Atomic Consequence Commit ─────────────────────
# Lua script for atomic effect application. All consequence writes happen
# in a single EVAL call — no race conditions, no partial state.
#
# KEYS[1] = workflow:effect_applied:{workflow_id}  (idempotency guard, permanent)
# KEYS[2] = world_state                            (global sim state hash)
# KEYS[3] = federation:effects_cycle:{cycle_id}      (per-cycle cap tracking, TTL'd)
# KEYS[4] = workflow:effect_receipt:{workflow_id}  (permanent receipt)
# KEYS[5] = npc_outcome_effect:{source_npc}        (councilor context)
# KEYS[6] = {institution_id}:outcome_reputation    (may be empty string)
#
# ARGV[1]  = cutoff_epoch  (float string or "0" if cutoff disabled)
# ARGV[2]  = wf_created_epoch (float string, or "" if created_at invalid/missing)
# ARGV[3]  = execution_cycle_id (string)
# ARGV[4]  = outcome ("approved" or "rejected")
# ARGV[5]  = artifact_kind ("proposal", "analysis", or other)
# ARGV[6]  = title (string)
# ARGV[7]  = source_npc (string)
# ARGV[8]  = institution_id (may be empty)
# ARGV[9]  = workflow_id (string)
# ARGV[10] = timestamp (ISO string)
# ARGV[11] = effect definitions as JSON: [{"key":"morale","delta":3.0}, ...]
# ARGV[12..N] = cap values (one per effect, matching order of effects_json)
# ARGV[12+N] = cap_hash_ttl (integer seconds)
#
# Return values (RESP2 arrays):
#   {"applied", cycle_id}          — effect committed successfully
#   {"already_applied"}            — idempotency guard caught a duplicate
#   {"skipped_invalid_created_at"} — created_at was missing or malformed
#   {"skipped_cutoff"}             — workflow created before deployment cutoff

_APPLY_EFFECTS_LUA = """
-- ── 1. Idempotency guard (permanent SET NX — no TTL) ──
local already = redis.call("GET", KEYS[1])
if already then
    return {"already_applied"}
end
redis.call("SET", KEYS[1], "1")

local cutoff_epoch = tonumber(ARGV[1]) or 0
local wf_created_epoch_str = ARGV[2]
local cycle_id = ARGV[3]
local outcome = ARGV[4]
local artifact_kind = ARGV[5]
local title = ARGV[6]
local source_npc = ARGV[7]
local institution_id = ARGV[8]
local workflow_id = ARGV[9]
local timestamp = ARGV[10]
local effects_json = ARGV[11]

-- ── 2. Malformed/missing created_at → skip atomically ──
if wf_created_epoch_str == "" then
    redis.call("HSET", KEYS[4],
        "ts", timestamp,
        "outcome", outcome,
        "artifact_kind", artifact_kind,
        "artifact_title", string.sub(title, 1, 60),
        "source_councilor_id", source_npc,
        "institution_id", institution_id,
        "execution_cycle_id", cycle_id,
        "status", "skipped_invalid_created_at",
        "reason", "missing_or_malformed_created_at",
        "requested", "[]",
        "applied", "[]",
        "before", "{}",
        "after", "{}",
        "reasons", "{}",
        "workflow_id", workflow_id,
        "effects", "[]")
    return {"skipped_invalid_created_at"}
end

-- ── 3. Deployment cutoff check ──
local wf_epoch = tonumber(wf_created_epoch_str) or 0
if cutoff_epoch > 0 and wf_epoch < cutoff_epoch then
    redis.call("HSET", KEYS[4],
        "ts", timestamp,
        "outcome", outcome,
        "artifact_kind", artifact_kind,
        "artifact_title", string.sub(title, 1, 60),
        "source_councilor_id", source_npc,
        "institution_id", institution_id,
        "execution_cycle_id", cycle_id,
        "status", "skipped_cutoff",
        "reason", "workflow_created_before_deployment_cutoff",
        "requested", "[]",
        "applied", "[]",
        "before", "{}",
        "after", "{}",
        "reasons", "{}",
        "workflow_id", workflow_id,
        "effects", "[]")
    return {"skipped_cutoff"}
end

-- ── 4. Parse effects JSON ──
local effects = cjson.decode(effects_json)

local requested = {}
local applied = {}
local before_vals = {}
local after_vals = {}
local reasons = {}

local num_effects = #effects
local cap_start_idx = 12  -- caps start at ARGV[12]
local ttl = tonumber(ARGV[cap_start_idx + num_effects]) or 604800

for i, eff in ipairs(effects) do
    local key = eff.key
    local delta = tonumber(eff.delta)
    if not delta then delta = 0 end

    local cap = tonumber(ARGV[cap_start_idx + i - 1])
    if not cap then cap = 999999 end

    requested[key] = delta

    -- Read current world state
    local raw = redis.call("HGET", KEYS[2], key)
    local current_val = 50.0
    if raw then current_val = tonumber(raw) or 50.0 end
    before_vals[key] = current_val

    -- Read cumulative delta for this cycle from cycle_key hash
    local cum_raw = redis.call("HGET", KEYS[3], key)
    local cumulative = 0.0
    if cum_raw then cumulative = tonumber(cum_raw) or 0.0 end

    local proposed_cumulative = cumulative + delta

    local actual_delta = delta
    local actual_cumulative = proposed_cumulative
    local effect_reason = "fully_applied"

    -- Cap check: absolute cumulative must not exceed cap
    if math.abs(proposed_cumulative) > cap then
        local remaining = cap - math.abs(cumulative)
        if remaining <= 0 then
            actual_delta = 0
            actual_cumulative = cumulative
            effect_reason = "cycle_cap_reached"
        else
            actual_delta = remaining * (delta > 0 and 1 or -1)
            actual_cumulative = cumulative + actual_delta
            effect_reason = "partially_capped"
        end
    end

    -- Apply world state change (clamped to [0, 100])
    local new_val = current_val + actual_delta
    local final_val = new_val
    if final_val < 0 then
        final_val = 0
        if actual_delta ~= 0 then effect_reason = "world_boundary_clamped" end
    end
    if final_val > 100 then
        final_val = 100
        if actual_delta ~= 0 then effect_reason = "world_boundary_clamped" end
    end

    -- Round FIRST, then compute the actual committed delta
    final_val = math.floor(final_val * 10 + 0.5) / 10
    local committed_delta = final_val - current_val

    -- Store rounded value
    redis.call("HSET", KEYS[2], key, tostring(final_val))

    -- Update cumulative cap tracker with committed delta (not requested)
    actual_cumulative = cumulative + committed_delta
    redis.call("HSET", KEYS[3], key, tostring(actual_cumulative))

    applied[key] = committed_delta
    after_vals[key] = final_val
    reasons[key] = effect_reason
end

-- Set TTL on cap hash so it expires after the retention window
redis.call("EXPIRE", KEYS[3], ttl)

-- ── 5. Write structured receipt (permanent) ──
redis.call("HSET", KEYS[4],
    "ts", timestamp,
    "outcome", outcome,
    "artifact_kind", artifact_kind,
    "artifact_title", string.sub(title, 1, 60),
    "source_councilor_id", source_npc,
    "institution_id", institution_id,
    "execution_cycle_id", cycle_id,
    "status", "applied",
    "reason", "effects_committed",
    "requested", cjson.encode(requested),
    "applied", cjson.encode(applied),
    "before", cjson.encode(before_vals),
    "after", cjson.encode(after_vals),
    "reasons", cjson.encode(reasons),
    "workflow_id", workflow_id,
    "effects", cjson.encode(applied))

-- ── 6. NPC outcome effect (latest result for councilor context) ──
local mood = "validated"
if outcome == "rejected" then mood = "frustrated" end
redis.call("HSET", KEYS[5],
    "ts", timestamp,
    "outcome", outcome,
    "artifact_kind", artifact_kind,
    "mood_effect", mood,
    "effects", cjson.encode(applied),
    "workflow_id", workflow_id,
    "title", string.sub(title, 1, 60))

-- ── 7. Institution reputation ──
if institution_id ~= "" and KEYS[6] ~= "" then
    local rep_delta = 1
    if outcome == "rejected" then rep_delta = -1 end
    local current = tonumber(redis.call("GET", KEYS[6]) or "0") or 0
    redis.call("SET", KEYS[6], tostring(current + rep_delta))
end

return {"applied", cycle_id}
"""


def _resolve_deltas(outcome, artifact_kind):
    """Return the list of (key, delta) tuples for a given outcome and artifact kind."""
    if outcome == "approved":
        if artifact_kind == "proposal":
            return [("morale", 3.0), ("stability", 2.0), ("resource_abundance", -2.0)]
        elif artifact_kind == "analysis":
            return [("stability", 2.5)]
        else:
            return [("morale", 2.0)]
    else:  # rejected
        return [("morale", -4.0), ("stability", -2.0)]


def _to_epoch(wf_created):
    """Convert an ISO timestamp string to epoch float. Returns None if invalid."""
    if not wf_created:
        return None
    try:
        from datetime import datetime as _dt
        dt = _dt.fromisoformat(wf_created)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _apply_outcome_effects(r, source_npc, record, outcome, timestamp, workflow_id="", execution_cycle_id=""):
    """Apply concrete world-state and NPC-state mutations when a workflow
    reaches a terminal state.

    Phase 1A.2 — Atomic Consequence Commit:
    - Idempotency: permanent SET NX on workflow:effect_applied:{workflow_id} (inside Lua)
    - Deployment cutoff: pre-converted to epoch, enforced inside Lua atomically
    - Malformed created_at: wf_created_epoch passed as "" to Lua, handled atomically
    - Per-execution-cycle aggregate caps: tracked in KEYS[3] hash, TTL'd, enforced in Lua
    - All writes (world_state, cap tracker, receipt, NPC effect, institution rep) are
      in a single atomic Lua EVAL — no partial state on crash
    - Decimal precision: world_state stored with 1 decimal precision (in Lua)
    - Structured receipts with reason field (fully_applied / partially_capped / etc.)

    Returns the result array from Lua (e.g. ["applied", cycle_id]).
    """
    applied_key = EFFECT_APPLIED_KEY.format(workflow_id=workflow_id)
    workflow_epoch = _to_epoch(record.get("created_at", ""))
    cutoff_epoch = float(_to_epoch(EFFECTS_CUTOFF_TIMESTAMP)) if EFFECTS_CUTOFF_TIMESTAMP else 0.0

    artifact_kind = record.get("artifact_kind", "")
    title = record.get("title", "")
    institution_id = record.get("institution_id", "")
    effect_deltas = _resolve_deltas(outcome, artifact_kind)

    effects_json = json.dumps([{"key": k, "delta": d} for k, d in effect_deltas])
    cap_args = [str(EFFECTS_CAPS.get(k, 999999.0)) for k, _ in effect_deltas]

    receipt_key = EFFECT_RECEIPT_KEY.format(workflow_id=workflow_id)
    npc_effect_key = f"npc_outcome_effect:{source_npc}"
    inst_rep_key = f"{institution_id}:outcome_reputation" if institution_id else ""
    cycle_key = f"federation:effects_cycle:{execution_cycle_id}" if execution_cycle_id else "federation:effects_cycle:unknown"

    keys = [
        applied_key,
        "world_state",
        cycle_key,
        receipt_key,
        npc_effect_key,
        inst_rep_key,
    ]

    # ARGV: cutoff_epoch, wf_created_epoch ("" if invalid), cycle_id, outcome,
    #       artifact_kind, title, source_npc, institution_id, workflow_id,
    #       timestamp, effects_json, cap values..., cap_hash_ttl
    args = [
        str(cutoff_epoch),
        str(workflow_epoch) if workflow_epoch else "",  # "" = invalid/missing
        execution_cycle_id,
        outcome,
        artifact_kind,
        title[:60],
        source_npc,
        institution_id,
        workflow_id,
        timestamp,
        effects_json,
    ] + cap_args + [str(CAP_HASH_TTL_SEC)]

    # ── Execute atomic Lua script ──
    result = r.eval(_APPLY_EFFECTS_LUA, len(keys), *keys, *args)

    if isinstance(result, list):
        if len(result) > 0 and result[0] == "already_applied":
            log.debug(
                "[outcomes] workflow %s: effect already applied (Lua idempotency), skipping",
                workflow_id,
            )
            return (False, True, "already_applied", [])
        if len(result) > 0 and result[0] in ("skipped_invalid_created_at", "skipped_cutoff"):
            log.info(
                "[outcomes] workflow %s: %s, effects skipped",
                workflow_id, result[0],
            )
            return (False, True, result[0], [])
        if len(result) > 0 and result[0] == "applied":
            cycle_id = result[1] if len(result) > 1 else execution_cycle_id
            effect_strs = [f"{k}{d:+.1f}" for k, d in effect_deltas]
            log.info(
                "[outcomes] %s workflow %s: %s kind=%s effects=[%s] cycle=%s (atomic)",
                source_npc, workflow_id, outcome, artifact_kind,
                " ".join(effect_strs), cycle_id,
            )
            return (True, True, "applied", effect_strs)

    log.warning(
        "[outcomes] workflow %s: unexpected Lua return %r",
        workflow_id, result,
    )
    return (False, False, "unexpected", [])


def _adj_world(r, key, delta, faction_affil):
    """Add *delta* to a world_state key, clamped to [0, 100].

    A *faction_affil* argument is accepted for future per-faction
    accounting but currently world_state is global.
    """
    try:
        raw = r.hget("world_state", key)
        current = float(raw) if raw else 50.0
        new_val = max(0.0, min(100.0, current + delta))
        r.hset("world_state", key, str(int(round(new_val))))
    except (ValueError, TypeError):
        pass


def _councilor_affiliation(char_id):
    """Return a best-effort faction affiliation for a councilor char_id."""
    try:
        return char_id  # placeholder; real affiliations come from NPC roster
    except Exception:
        return ""


def _record_outcome(r, workflow_id, record, new_status, execution_cycle_id=""):
    if new_status not in TERMINAL_STATES:
        return
    source_npc = record.get("source_councilor_id", "")
    if not source_npc:
        return
    wf_type = record.get("type", "")
    outcome = "approved" if new_status in ("ratified", "endorsed", "approved") else "rejected"
    timestamp = _now_iso()
    hist_key = NPC_OUTCOME_HISTORY_KEY.format(npc_id=source_npc)
    r.hincrby(hist_key, outcome, 1)
    recent_key = NPC_RECENT_OUTCOMES_KEY.format(npc_id=source_npc)
    entry = json.dumps({"workflow_id": workflow_id, "type": wf_type, "outcome": outcome, "ts": timestamp})
    r.lpush(recent_key, entry)
    r.ltrim(recent_key, 0, MAX_RECENT_OUTCOMES - 1)

    # ── Mark workflow as effect_pending before applying ──
    # This allows reconcile_pending_effects() to find and retry workflows
    # that crashed between status change and effect commit.
    r.hset(workflow_id, mapping={"effect_pending": "1"})
    r.sadd(EFFECTS_PENDING_KEY, workflow_id)

    # ── Apply concrete world-state effects (atomic Lua, Phase 1A.2) ──
    # The Lua script handles idempotency via SET NX on workflow:effect_applied:{id}
    # Returns (committed, resolved, reason, effect_strs). Clear effect_pending on any resolved outcome.
    try:
        committed, resolved, reason, _ = _apply_outcome_effects(
            r, source_npc, record, outcome, timestamp, workflow_id, execution_cycle_id
        )
    except redis.RedisError as e:
        log.exception(
            "[outcomes] workflow %s: atomic effect commit failed: %s",
            workflow_id, e,
        )
        committed, resolved, reason = False, False, "redis_error"

    # ── Clear effect_pending when outcome is resolved (success, skip, or already applied) ──
    if resolved:
        r.hset(workflow_id, mapping={"effect_pending": "0"})
        r.srem(EFFECTS_PENDING_KEY, workflow_id)
    else:
        log.warning(
            "[outcomes] workflow %s: effect NOT resolved (reason=%s), effect_pending remains 1 for reconciliation",
            workflow_id, reason,
        )


def backfill_effects_pending_set(r):
    """One-time migration: populate workflow:effects_pending from existing effect_pending=1 flags.

    Checks for a completion marker before scanning. Scans completed workflows
    once and adds any with effect_pending=1 to the dedicated pending set.
    Uses SADD's integer return value to count only newly-added IDs.
    Sets the marker only after a successful complete scan.
    """
    if r.get(BACKFILL_MARKER_KEY):
        return {"migrated": 0, "skipped": "already_completed"}

    migrated = 0
    for wf_id in r.smembers(COMPLETED_WORKFLOWS_KEY):
        rec = r.hgetall(wf_id)
        if rec.get("effect_pending") == "1":
            added = r.sadd(EFFECTS_PENDING_KEY, wf_id)
            migrated += added
    r.set(BACKFILL_MARKER_KEY, "1")
    if migrated:
        log.info("[backfill] migrated %d workflows into workflow:effects_pending", migrated)
    return {"migrated": migrated}


def reconcile_pending_effects(r, execution_cycle_id=""):
    """Retry outcome effects for workflows left pending by prior crashes.

    Uses the dedicated ``workflow:effects_pending`` set so runtime cost is
    proportional to unresolved failures (normally zero or a handful) rather
    than the full completed-workflow history.

    The Lua script's idempotency guard (SET NX on workflow:effect_applied:{id})
    prevents double-application.

    Returns a summary dict with counts.
    """
    if not execution_cycle_id:
        import uuid
        execution_cycle_id = f"reconcile_{uuid.uuid4().hex[:12]}"

    pending_ids = sorted(r.smembers(EFFECTS_PENDING_KEY))

    applied_count = 0
    skipped_count = 0

    for wf_id in pending_ids:
        record = r.hgetall(wf_id)
        source_npc = record.get("source_councilor_id", "")
        if not source_npc:
            skipped_count += 1
            r.srem(EFFECTS_PENDING_KEY, wf_id)
            r.hset(wf_id, mapping={"effect_pending": "0"})
            continue

        status = record.get("status", "")
        if status not in TERMINAL_STATES:
            skipped_count += 1
            r.srem(EFFECTS_PENDING_KEY, wf_id)
            r.hset(wf_id, mapping={"effect_pending": "0"})
            continue

        outcome = "approved" if status in ("ratified", "endorsed", "approved") else "rejected"
        timestamp = _now_iso()

        # Re-apply — Lua SET NX guard prevents double-application
        try:
            committed, resolved, reason, _ = _apply_outcome_effects(r, source_npc, record, outcome, timestamp,
                                            wf_id, execution_cycle_id)
        except redis.RedisError as e:
            log.exception(
                "[reconcile] workflow %s: atomic effect commit failed: %s",
                wf_id, e,
            )
            committed, resolved, reason = False, False, "redis_error"
        if resolved:
            if committed:
                applied_count += 1
            else:
                skipped_count += 1
            r.hset(wf_id, mapping={"effect_pending": "0"})
            r.srem(EFFECTS_PENDING_KEY, wf_id)

    if applied_count or skipped_count:
        log.info(
            "[reconcile] pending effects: %d applied, %d skipped (cycle=%s)",
            applied_count, skipped_count, execution_cycle_id,
        )

    return {
        "pending_found": len(pending_ids),
        "applied": applied_count,
        "skipped": skipped_count,
        "cycle_id": execution_cycle_id,
    }


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
