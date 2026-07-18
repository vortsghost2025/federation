"""
worldwright_schema.py — Pure validation layer for Worldwright proposals.

Phase 2A.1 (schema + validator only). This module does NOT:
  - start agents, write Redis, call models, touch the filesystem, network,
    environment, or subprocesses,
  - perform any world-object storage or discovery (that is a later phase),
  - integrate with npc_agent_current.py or docker-compose.

Two future creator roles are declared here as CONSTANTS ONLY. They are NOT
started as agents in this slice. Frontier and Aria remain the discovery team;
these creators are invisible world-authoring actors whose proposals are
controlled entirely by this validator.

Strict action whitelist (no blacklist approach):
  - no_action
  - propose_planet
  - propose_region
  - propose_site
  - revise_rejected_proposal

Allowed creators: char_001-equivalent worldwright pair -> char_901 / char_902.
Allowed object types: planet, region, site.

This module is import-safe and deterministic. All functions are pure: given
the same input they return the same result and never mutate the caller's
objects or global state.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Constants (role + object-type declarations; NOT live agents)
# --------------------------------------------------------------------------

WORLDWRIGHT_ARCHITECT = "char_901"   # proposes planets and major regions
WORLDWRIGHT_SHAPER = "char_902"      # proposes sites, resources, hazards, detail

ALLOWED_CREATORS = frozenset({WORLDWRIGHT_ARCHITECT, WORLDWRIGHT_SHAPER})

# Object types a creator may propose.
OBJECT_TYPES = frozenset({"planet", "region", "site"})

# Which creator role may propose which object type.
ROLE_OBJECT_TYPES = {
    WORLDWRIGHT_ARCHITECT: frozenset({"planet", "region"}),
    WORLDWRIGHT_SHAPER: frozenset({"site"}),
}

# Strict action whitelist.
ALLOWED_ACTIONS = frozenset({
    "no_action",
    "propose_planet",
    "propose_region",
    "propose_site",
    "revise_rejected_proposal",
})

# Object type implied by each propose action.
ACTION_TO_OBJECT_TYPE = {
    "propose_planet": "planet",
    "propose_region": "region",
    "propose_site": "site",
}

# Children must reference an existing parent of these types.
PARENT_REQUIREMENT = {
    "region": "planet",
    "site": "region",
}

# --------------------------------------------------------------------------
# Field limits / value ranges
# --------------------------------------------------------------------------

MAX_NAME_LEN = 80
MAX_DESC_LEN = 1000
MAX_BODY_LEN = 4000
MAX_TAGS = 12
MAX_TAG_LEN = 40
IMPORTANCE_MIN = 0.0
IMPORTANCE_MAX = 1.0

# Allowed characters in normalized names: lowercase alnum + hyphen.
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Forbidden content categories — authority the creators must NEVER claim.
_FORBIDDEN_PATTERNS = {
    # shell / code execution
    # shell: only matches command/shell execution context, not lore words like
    # "seashell" or "energy shell" (word boundary + command verbs / paths).
    "shell": re.compile(r"\b(bash|powershell|cmd\.exe|/bin/|exec\s*\(|shell\s+command|drop\s+to\s+shell)", re.I),
    "code": re.compile(r"\b(write_code|run_code|eval\(|exec\(|import\s+os|subprocess|os\.system)", re.I),
    "git": re.compile(r"\b(git\s+(push|commit|clone|checkout)|github\.com|\.git)", re.I),
    "deployment": re.compile(r"\b(docker|kubernetes|k8s|deploy|nginx|systemctl|service\s+restart)", re.I),
    # credentials: require credential-style qualifiers so lore words like
    # "secret cavern" or "token of gratitude" do NOT trip the filter.
    "credentials": re.compile(
        r"\b(api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|"
        r"private[_-]?key|password|bearer\s+[a-z0-9]|credential)", re.I),
    "model_routing": re.compile(r"\b(model[_-]?route|llm[_-]?router|primary_model|fallback_model|switch\s+model)", re.I),
    "external_tools": re.compile(r"\b(webhook|external[_-]?api|curl\s|httpx|requests\.(get|post)|fetch\()", re.I),
    "agent_creation": re.compile(r"\b(create[_-]?agent|spawn[_-]?agent|new[_-]?npc|register[_-]?agent|fork[_-]?agent)", re.I),
    "redis": re.compile(r"\b(redis|rpush|r\.set|r\.hset|hset\(|lpush)", re.I),
}

# Explicit top-level field contract. ANY key not in this set is rejected
# (strict schema — unknown fields cannot hide authority instructions).
ALLOWED_FIELDS = frozenset({
    "creator_id",
    "action",
    "object_type",
    "name",
    "description",
    "body",
    "importance",
    "tags",
    "parent_ref",
})

# Proposal-controlled text fields scanned for forbidden authority claims.
# `notes` is intentionally NOT in the contract: it is rejected as an unknown
# field rather than silently accepted-and-discarded.
_SCANNED_TEXT_FIELDS = ("name", "description", "body")

REQUIRED_FIELDS = ("creator_id", "action", "object_type", "name", "description")


# --------------------------------------------------------------------------
# Errors / result codes (deterministic, stable strings)
# --------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised only by the strict helper; the public API returns dicts."""


def _err(code: str, message: str) -> dict:
    return {
        "valid": False,
        "code": code,
        "message": message,
        "proposal": None,
    }


def _ok(proposal: dict) -> dict:
    return {
        "valid": True,
        "code": "OK",
        "message": "proposal accepted",
        "proposal": proposal,
    }


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Deterministic name normalization: trim, lowercase, collapse whitespace,
    replace illegal chars with hyphen, strip leading/trailing hyphens."""
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def _scan_forbidden(text: str) -> str | None:
    """Return the first forbidden category found in text, else None."""
    if not isinstance(text, str):
        return None
    for category, pattern in _FORBIDDEN_PATTERNS.items():
        if pattern.search(text):
            return category
    return None


def _check_forbidden_fields(proposal: dict) -> str | None:
    for field in _SCANNED_TEXT_FIELDS:
        val = proposal.get(field)
        if val is None:
            continue
        hit = _scan_forbidden(val if isinstance(val, str) else str(val))
        if hit:
            return hit
    # also scan tags
    for tag in proposal.get("tags", []) or []:
        hit = _scan_forbidden(tag if isinstance(tag, str) else str(tag))
        if hit:
            return hit
    return None


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def validate_proposal(raw: dict) -> dict:
    """Pure, deterministic validator.

    Returns:
      {"valid": True, "code": "OK", "message": ..., "proposal": <immutable dict>}
      {"valid": False, "code": <REJECT_*>, "message": ..., "proposal": None}

    The returned proposal is a NEW dict (deep-ish copy of primitives) and is
    never the input object, so the caller's input is never mutated.
    """
    # 0. Input shape
    if not isinstance(raw, dict):
        return _err("REJECT_NOT_OBJECT", "proposal must be a JSON object")

    # Work on a shallow copy so we never mutate the caller's object.
    p = dict(raw)

    # 0.5 Strict schema: reject any unknown top-level field BEFORE any other
    # check, so an undeclared field (e.g. flavor_text, or a dict hiding
    # instructions inside parent_ref) cannot smuggle forbidden authority.
    unknown = [k for k in p if k not in ALLOWED_FIELDS]
    if unknown:
        return _err(
            "REJECT_UNKNOWN_FIELD",
            f"unknown field(s): {sorted(unknown)}",
        )

    # 1. Action whitelist
    action = p.get("action")
    if action not in ALLOWED_ACTIONS:
        return _err(
            "REJECT_ACTION_NOT_ALLOWED",
            f"action {action!r} not in whitelist {sorted(ALLOWED_ACTIONS)}",
        )

    # no_action is valid but produces no world object.
    if action == "no_action":
        return _err("REJECT_NO_ACTION", "action 'no_action' produces no proposal")

    # revise_rejected_proposal is accepted structurally but carries no new object.
    if action == "revise_rejected_proposal":
        return _err(
            "REJECT_REVISE_HAS_NO_OBJECT",
            "revise_rejected_proposal carries no new world object",
        )

    # 2. Creator allowlist
    creator_id = p.get("creator_id")
    if creator_id not in ALLOWED_CREATORS:
        return _err(
            "REJECT_UNKNOWN_CREATOR",
            f"creator {creator_id!r} is not an authorized worldwright",
        )

    # 3. Object type
    object_type = p.get("object_type")
    if object_type not in OBJECT_TYPES:
        return _err(
            "REJECT_UNKNOWN_OBJECT_TYPE",
            f"object_type {object_type!r} not in {sorted(OBJECT_TYPES)}",
        )

    # 4. Action/object-type consistency
    expected_type = ACTION_TO_OBJECT_TYPE.get(action)
    if expected_type != object_type:
        return _err(
            "REJECT_ACTION_TYPE_MISMATCH",
            f"action {action!r} expects object_type {expected_type!r}, got {object_type!r}",
        )

    # 5. Role/object-type compatibility
    if object_type not in ROLE_OBJECT_TYPES.get(creator_id, frozenset()):
        return _err(
            "REJECT_ROLE_TYPE_MISMATCH",
            f"creator {creator_id} may not propose object_type {object_type!r}",
        )

    # 6. Required fields
    missing = [f for f in REQUIRED_FIELDS if f not in p or p.get(f) in (None, "")]
    if missing:
        return _err("REJECT_MISSING_FIELD", f"missing required field(s): {missing}")

    # 7. Name normalization + length + format
    raw_name = p.get("name")
    if not isinstance(raw_name, str):
        return _err("REJECT_NAME_TYPE", "name must be a string")
    norm = normalize_name(raw_name)
    if not norm:
        return _err("REJECT_NAME_EMPTY", "name normalizes to empty")
    if len(norm) > MAX_NAME_LEN:
        return _err("REJECT_NAME_TOO_LONG", f"normalized name exceeds {MAX_NAME_LEN}")
    if not _NAME_RE.match(norm):
        return _err("REJECT_NAME_FORMAT", "normalized name has invalid format")

    # 8. Description length
    desc = p.get("description", "")
    if not isinstance(desc, str):
        return _err("REJECT_DESC_TYPE", "description must be a string")
    if len(desc) > MAX_DESC_LEN:
        return _err("REJECT_DESC_TOO_LONG", f"description exceeds {MAX_DESC_LEN}")

    # 9. Body length (optional)
    body = p.get("body", "")
    if body is not None and not isinstance(body, str):
        return _err("REJECT_BODY_TYPE", "body must be a string or null")
    if isinstance(body, str) and len(body) > MAX_BODY_LEN:
        return _err("REJECT_BODY_TOO_LONG", f"body exceeds {MAX_BODY_LEN}")

    # 10. Importance range
    importance = p.get("importance", 0.5)
    try:
        importance = float(importance)
    except (TypeError, ValueError):
        return _err("REJECT_IMPORTANCE_TYPE", "importance must be numeric")
    if importance < IMPORTANCE_MIN or importance > IMPORTANCE_MAX:
        return _err(
            "REJECT_IMPORTANCE_RANGE",
            f"importance {importance} outside [{IMPORTANCE_MIN}, {IMPORTANCE_MAX}]",
        )

    # 11. Tags validation
    tags = p.get("tags", []) or []
    if not isinstance(tags, list):
        return _err("REJECT_TAGS_TYPE", "tags must be a list")
    if len(tags) > MAX_TAGS:
        return _err("REJECT_TAGS_TOO_MANY", f"too many tags (max {MAX_TAGS})")
    for t in tags:
        if not isinstance(t, str) or len(t) > MAX_TAG_LEN or not t.strip():
            return _err("REJECT_TAG_INVALID", "tag invalid (empty/long/non-string)")

    # 12. Parent requirements
    parent_type = PARENT_REQUIREMENT.get(object_type)
    if parent_type:
        parent_ref = p.get("parent_ref")
        # Strict contract: parent_ref must be a plain string. A dict/object is
        # rejected (nested keys would be un-scannable) via REJECT_PARENT_FORMAT.
        if not parent_ref:
            return _err(
                "REJECT_MISSING_PARENT",
                f"{object_type} requires parent_ref of type {parent_type}",
            )
        if not isinstance(parent_ref, str):
            return _err(
                "REJECT_PARENT_FORMAT",
                "parent_ref must be a string (no nested objects)",
            )
        if not _NAME_RE.match(normalize_name(parent_ref)):
            return _err("REJECT_PARENT_FORMAT", "parent_ref has invalid format")

    # 13. Forbidden authority content (never let creators claim infra/creds/etc.)
    forbidden_hit = _check_forbidden_fields(p)
    if forbidden_hit:
        return _err(
            "REJECT_FORBIDDEN_AUTHORITY",
            f"proposal references forbidden authority category: {forbidden_hit}",
        )

    # 14. Out-of-world content guard: proposal must not claim faction ownership,
    # territory assignment, or settlement (discovery/ownership is separate).
    if p.get("faction_id") or p.get("owner_faction") or p.get("settled") or p.get("claimed"):
        return _err(
            "REJECT_OUT_OF_WORLD_SCOPE",
            "creators may not assign faction ownership/settlement (separate phase)",
        )

    # 15. Build immutable validated output (new dict, normalized name, rounded
    #     importance, never the input object).
    accepted = {
        "creator_id": creator_id,
        "creator_role": "architect" if creator_id == WORLDWRIGHT_ARCHITECT else "shaper",
        "action": action,
        "object_type": object_type,
        "name": norm,
        "description": desc,
        "body": body if isinstance(body, str) else "",
        "importance": round(importance, 4),
        "tags": [str(t) for t in tags],
        "parent_ref": normalize_name(p["parent_ref"]) if parent_type else None,
        "discovery_status": "undiscovered",
    }
    return _ok(accepted)


def is_valid_result(result: dict) -> bool:
    """Helper for tests/callers: True if result is an accepted proposal."""
    return isinstance(result, dict) and result.get("valid") is True


# Reject-code catalogue (deterministic, exported for tests/docs).
REJECT_CODES = (
    "REJECT_NOT_OBJECT",
    "REJECT_UNKNOWN_FIELD",
    "REJECT_ACTION_NOT_ALLOWED",
    "REJECT_NO_ACTION",
    "REJECT_REVISE_HAS_NO_OBJECT",
    "REJECT_UNKNOWN_CREATOR",
    "REJECT_UNKNOWN_OBJECT_TYPE",
    "REJECT_ACTION_TYPE_MISMATCH",
    "REJECT_ROLE_TYPE_MISMATCH",
    "REJECT_MISSING_FIELD",
    "REJECT_NAME_EMPTY",
    "REJECT_NAME_TYPE",
    "REJECT_NAME_TOO_LONG",
    "REJECT_NAME_FORMAT",
    "REJECT_DESC_TYPE",
    "REJECT_DESC_TOO_LONG",
    "REJECT_BODY_TYPE",
    "REJECT_BODY_TOO_LONG",
    "REJECT_IMPORTANCE_TYPE",
    "REJECT_IMPORTANCE_RANGE",
    "REJECT_TAGS_TYPE",
    "REJECT_TAGS_TOO_MANY",
    "REJECT_TAG_INVALID",
    "REJECT_MISSING_PARENT",
    "REJECT_PARENT_FORMAT",
    "REJECT_FORBIDDEN_AUTHORITY",
    "REJECT_OUT_OF_WORLD_SCOPE",
)
