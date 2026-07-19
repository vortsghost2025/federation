"""S3A audit results and redaction.

Every plan or execution result is deterministic and redacted.

Do not include: credentials, environment values, raw private NPC conversations,
arbitrary exception strings, or personal absolute paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .s3a_action import S3A_SCHEMA_VERSION

RESULT_VERSION = "steward@0.3.0"

# Redaction patterns: secrets, env values, private content, exception strings,
# absolute personal paths.
_SECRET_KEYS = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|auth|private[_-]?key|credential)"
)
_ABS_PATH = re.compile(r"(^[A-Za-z]:\\\\|/home/|/Users/|/root/|C:\\\\|S:\\\\)")
_EXCEPTION_HINT = re.compile(r"Traceback|Error:|Exception", re.IGNORECASE)


@dataclass
class AuditResult:
    result_id: str
    action_id: str
    decision: str  # "committed" | "denied" | "conflict" | "replayed"
    mutation_status: str  # "applied" | "none"
    before_version: int
    after_version: int
    denial_reason: str
    approval_reference: Optional[str]
    idempotent_replay: bool
    redacted_evidence: Dict[str, Any]
    schema_version: str = RESULT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "action_id": self.action_id,
            "decision": self.decision,
            "mutation_status": self.mutation_status,
            "before_version": self.before_version,
            "after_version": self.after_version,
            "denial_reason": self.denial_reason,
            "approval_reference": self.approval_reference,
            "idempotent_replay": self.idempotent_replay,
            "redacted_evidence": self.redacted_evidence,
            "schema_version": self.schema_version,
        }


def make_result_id(action_id: str, decision: str, observed_at: str) -> str:
    material = json.dumps(
        {
            "action_id": action_id,
            "decision": decision,
            "observed_at": observed_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "res_" + hashlib.sha256(material).hexdigest()


def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, v) for v in value]
    if isinstance(value, str):
        if _SECRET_KEYS.search(key):
            return "<redacted:secret>"
        if _ABS_PATH.search(value):
            return "<redacted:path>"
        if _EXCEPTION_HINT.search(value):
            return "<redacted:exception>"
        if _looks_like_private_npc(value):
            return "<redacted:private_npc_content>"
    return value


_PRIVATE_NPC_HINT = re.compile(
    r"(?i)(private[_ -]?message|direct[_ -]?dm|whisper|confession|intimate)"
)


def _looks_like_private_npc(value: str) -> bool:
    return bool(_PRIVATE_NPC_HINT.search(value))


def redact_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a redacted copy; input is never mutated."""
    return _redact_value("evidence", copy.deepcopy(evidence))
