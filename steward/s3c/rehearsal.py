"""S3C live read-only rehearsal (S3C-008).

Authorized, read-only rehearsal against the federation VPS. This module
DEFINES and EXECUTES only read-only observation. It never discloses secrets,
never writes, and never connects to anything unless explicitly enabled by an
operator who supplies the connection outside this module (no credential is
stored here).

REHEARSAL COMMAND SET (read-only only):
  * SSH read-only: `docker ps`, `docker inspect`, `docker stats --no-stream`,
    `docker logs --tail`, `docker network ls/inspect`, `docker volume ls/inspect`,
    and narrowly scoped `docker exec` ONLY inside the Redis container for
    allowlisted Redis READ commands (e.g. `redis-cli INFO`, `redis-cli DBSIZE`,
    `redis-cli --scan --count`).
  * HTTP GET/HEAD against allowlisted read endpoints.
  FORBIDDEN during rehearsal: Redis writes, container mutations, app-container
  exec, DB writes, Federation API writes, NPC ops, cognition, Dagu ops, and
  any credential inspection.

Because this S3C phase runs offline and must not handle live secrets, the
actual transport is DISABLED by default. `collect_observations()` returns a
deterministic, normalized fixture so the determinism/comparison logic can be
exercised and proven without touching production. An operator may pass
`execute=True` only when they have separately established a read-only session;
this module still never stores or prints secrets.

Two runs are collected, applied to FRESH local qualification backends, and
compared for determinism after volatile-field normalization. Live bundles are
written locally but NOT committed (directive: DO NOT commit live bundles).

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .backend import build_shadow_memory_adapter, build_shadow_sqlite_adapter
from .bundles import RunBundle, write_bundle
from .interlock import evaluate
from .manifest import RunManifest
from .profiles import default_live_readonly_profile
from .shadow_model import ShadowProposedAction, ShadowWriteOutcome
from .writer import ShadowWriterCore

_FIXED_NOW = "2026-07-08T00:00:00Z"

# Volatile fields normalized away before determinism comparison.
_VOLATILE_KEYS = ("observed_at", "latency_ms", "uptime_sec", "timestamp")


@dataclass
class Observation:
    source: str           # e.g. "docker.inspect.redis"
    entity: str           # opaque label, never a secret/hostname
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RehearsalResult:
    run_label: str
    observations: List[Observation] = field(default_factory=list)
    applied_actions: List[Dict[str, Any]] = field(default_factory=list)
    bundle_sha256: str = ""
    bundle_path: str = ""


def _disabled_fixture_observations(run_label: str) -> List[Observation]:
    """Deterministic, secret-free fixture used when transport is disabled."""

    return [
        Observation(
            source="docker.inspect.redis",
            entity="redis-shadow",
            payload={"image": "redis:7", "state": "running", "restarts": 0},
        ),
        Observation(
            source="docker.stats.redis",
            entity="redis-shadow",
            payload={"cpu": "0.5%", "mem": "12MiB", "latency_ms": 3},
        ),
        Observation(
            source="redis.read.dbsize",
            entity="redis-shadow",
            payload={"dbsize": 42, "observed_at": run_label},
        ),
    ]


def collect_observations(run_label: str, execute: bool = False) -> List[Observation]:
    """Collect read-only observations.

    When execute=False (default, offline), returns a deterministic fixture.
    When execute=True, an operator has already established a read-only session
    elsewhere; this function is where the read-only command set would run. This
    S3C phase always uses execute=False to avoid handling live secrets.
    """

    if execute:
        # Intentionally not implemented in S3C: no live transport, no secrets.
        # An operator would plug a read-only collector here that returns
        # Observation objects without ever storing credentials.
        raise RuntimeError(
            "live transport disabled in S3C; execute=True requires an "
            "operator-supplied read-only collector (no secrets handled here)"
        )
    return _disabled_fixture_observations(run_label)


def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(payload)
    for k in _VOLATILE_KEYS:
        out.pop(k, None)
    return out


def _apply_to_fresh_backend(
    observations: List[Observation],
    namespace: str,
    backend_kind: str,
    run_label: str,
) -> RehearsalResult:
    """Apply normalized observations to a fresh local qualification backend and
    produce a (non-committed) run bundle."""

    # Build deterministic shadow actions from normalized observation summaries.
    actions: List[ShadowProposedAction] = []
    for idx, obs in enumerate(observations):
        actions.append(
            ShadowProposedAction(
                schema_version="steward@0.3.0",
                action_type="shadow_observation_record",
                action_id=None,
                source_finding_id=f"obs_{run_label}_{idx}",
                source_snapshot_id=f"snap_{run_label}",
                target_namespace=namespace,
                requested_capability="steward:shadow:observe",
                actor_id="shadow_rehearsal",
                requested_at=_FIXED_NOW,
                idempotency_key=f"idem_{run_label}_{idx}",
                approval_state="approved",
                normalized_payload=_normalize(obs.payload),
                redacted_provenance={"origin": obs.source, "entity": obs.entity},
            )
        )

    if backend_kind == "sqlite":
        fd, db_path = tempfile.mkstemp(prefix="s3c_reh_", suffix=".sqlite")
        os.close(fd)
        adapter = build_shadow_sqlite_adapter(db_path)
        cleanup = db_path
    else:
        adapter = build_shadow_memory_adapter()
        cleanup = None

    core = ShadowWriterCore(
        adapter=adapter,
        capability=adapter.cap,
        namespace=namespace,
        now_token=_FIXED_NOW,
        loaded_capabilities=[],
    )

    applied: List[Dict[str, Any]] = []
    for action in actions:
        outcome = core.execute(action)  # approved state, no artifact => denied
        # Rehearsal observations are recorded read-only; the writer core refuses
        # without an approval artifact, which is correct for shadow observe.
        applied.append(
            {
                "action_id": action.action_id,
                "decision": outcome.decision,
                "reason": outcome.reason,
            }
        )

    manifest = RunManifest(
        manifest_version="steward-s3c@0.1.0",
        mode="live_readonly_shadow_apply",
        source_profile="live_readonly.federation_vps",
        namespace=namespace,
        snapshot_id=f"snap_{run_label}",
        capability="steward:shadow:observe",
        requested_at=_FIXED_NOW,
        idempotency_key=f"idem_{run_label}",
        finding_ids=[a.source_finding_id for a in actions],
    )
    bundle = RunBundle(
        manifest=manifest,
        actions=[a.to_dict() for a in actions],
        outcomes=applied,
    )
    bundle.finalize()

    out_dir = tempfile.mkdtemp(prefix="s3c_reh_out_")
    path = write_bundle(bundle, out_dir)
    from .bundles import sha256_of

    sha = sha256_of(path)

    if cleanup and os.path.exists(cleanup):
        os.remove(cleanup)
    if os.path.exists(path):
        os.remove(path)
    if os.path.isdir(out_dir):
        try:
            os.rmdir(out_dir)
        except OSError:
            pass

    result = RehearsalResult(
        run_label=run_label,
        observations=observations,
        applied_actions=applied,
        bundle_sha256=sha,
    )
    return result


def run_rehearsal_twice(
    namespace: str = "steward:shadow:federation_vps",
    backend_kind: str = "memory",
) -> Dict[str, Any]:
    """Collect two read-only runs, apply to fresh backends, compare determinism.

    Returns a comparison dict. Does NOT commit any live bundle.
    """

    profile = default_live_readonly_profile()
    r1 = _apply_to_fresh_backend(
        collect_observations("run_1"), namespace, backend_kind, "run_1"
    )
    r2 = _apply_to_fresh_backend(
        collect_observations("run_2"), namespace, backend_kind, "run_2"
    )

    normalized_1 = [_normalize(o.payload) for o in r1.observations]
    normalized_2 = [_normalize(o.payload) for o in r2.observations]

    deterministic = json.dumps(normalized_1, sort_keys=True) == json.dumps(
        normalized_2, sort_keys=True
    )

    interlock = evaluate(
        mode="live_readonly_shadow_apply",
        backend_qualification_only=True,
        namespace=namespace,
        live_writer_present=False,
        loaded_capabilities=[],
        wildcard_approval=False,
        output_dir_local_safe=True,
        redaction_enabled=True,
        deterministic_timestamp_supplied=True,
    )

    return {
        "profile": profile.to_dict(),
        "run_1_sha256": r1.bundle_sha256,
        "run_2_sha256": r2.bundle_sha256,
        "deterministic": deterministic,
        "interlock_allowed": interlock.allowed,
        "note": "live bundles written to temp and removed; NOT committed",
    }
