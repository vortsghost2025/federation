"""Centralized secret redaction for S2 adapter output (spec Section 5/6).

All snapshot JSON and stdout output MUST pass through ``redact_value`` before
leaving the process. The goal: never emit credentials, tokens, cookies, auth
headers, private keys, DB/Redis connection strings, private URLs, or
environment secrets.

Redaction is conservative: any value whose key *looks* sensitive is masked,
and any string that matches a credential-shape pattern is masked regardless of
key. This keeps the rule simple and hard to bypass.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Keys (case-insensitive) that always indicate sensitive content.
SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "access_key",
    "accesskey",
    "private_key",
    "privatekey",
    "privkey",
    "credential",
    "credentials",
    "auth",
    "authorization",
    "cookie",
    "set-cookie",
    "session",
    "sessionid",
    "session_id",
    "x-auth-token",
    "x-api-key",
    "connection_string",
    "connectionstring",
    "dsn",
    "bearer",
)

# Patterns that indicate sensitive values even with benign keys.
_CRED_PATTERNS = [
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)Basic\s+[A-Za-z0-9+/=]+"),
    re.compile(r"(?i)eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWT
    re.compile(r"(?i)redis://[^:\s]+:[^@\s]+@"),  # redis://user:pass@
    re.compile(r"(?i)postgres(ql)?://[^:\s]+:[^@\s]+@"),  # postgres://user:pass@
    re.compile(r"(?i)amqp://[^:\s]+:[^@\s]+@"),
    re.compile(r"(?i)mongodb(\+srv)?://[^:\s]+:[^@\s]+@"),
    re.compile(r"(?i)sk-[A-Za-z0-9]{20,}"),  # openai-style
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)AIza[0-9A-Za-z_\-]{30,}"),  # google-style
]

REDACTED = "***REDACTED***"


def _key_is_sensitive(key: str) -> bool:
    k = key.lower().strip()
    if k in SENSITIVE_KEYS:
        return True
    # Substring matches for compound keys (e.g. "db_password_hash").
    return any(s in k for s in SENSITIVE_KEYS)


def _value_is_sensitive_str(value: str) -> bool:
    return any(p.search(value) for p in _CRED_PATTERNS)


def redact_value(value: Any) -> Any:
    """Recursively redact sensitive keys/values from any JSON-like structure."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if _key_is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = redact_value(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        if _value_is_sensitive_str(value):
            return REDACTED
        return value
    if isinstance(value, (bytes, bytearray)):
        # Bytes are never safe to echo verbatim -- decode and redact. If the
        # decoded text matches a credential pattern it is masked; otherwise we
        # still avoid dumping raw bytes by returning a normalized redaction.
        try:
            decoded = bytes(value).decode("utf-8", "replace")
        except Exception:
            decoded = ""
        if _value_is_sensitive_str(decoded):
            return REDACTED
        return REDACTED
    return value


def redact_credentials_strong(value: Any) -> Any:
    """Always-on credential masking. Unlike ``redact_value`` (which can be
    toggled off via --no-redact for structural reasons), this pass MUST run on
    any value leaving the process so raw secrets are never emitted."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _key_is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = redact_credentials_strong(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_credentials_strong(v) for v in value]
    if isinstance(value, str):
        if _value_is_sensitive_str(value):
            return REDACTED
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            decoded = bytes(value).decode("utf-8", "replace")
        except Exception:
            decoded = ""
        if _value_is_sensitive_str(decoded):
            return REDACTED
        return REDACTED
    return value


def redact_json_text(text: str) -> str:
    """Redact a JSON string; returns original text unchanged if not valid JSON."""
    try:
        data = __import__("json").loads(text)
    except Exception:
        # Could be plain text with embedded secrets; run regex pass on the raw.
        out = text
        for p in _CRED_PATTERNS:
            out = p.sub(REDACTED, out)
        return out
    return __import__("json").dumps(redact_value(data), sort_keys=True, indent=2)
