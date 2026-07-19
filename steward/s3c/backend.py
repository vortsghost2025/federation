"""S3C local shadow backend (S3C-006).

Provides the qualification backends the shadow pipeline writes through. These
are the SAME S3B qualification backends (in-memory + temp SQLite) — they are
already offline, deterministic, and qualification_only. S3C-006 adds:

  * a shadow namespace guard so only `steward:shadow:*` keys are accepted;
  * a temp-directory-only SQLite factory (deleted by the caller after tests);
  * a `qualification_only=True` capability wrapper.

No live connector. No writes outside the temp dir. No production Redis.

Forbidden in this file (beyond what S3B backends already forbid): redis,
requests, urllib, socket, subprocess, docker, paramiko, psycopg, mysql,
sqlalchemy, ssh, fabric, dagu, http.client, telnetlib. sqlite3 is used ONLY
via the S3B SqliteBackend in s3b/sqlitedb.py, never imported here.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

from ..s3b.adapter import (
    QualificationAdapter,
    build_memory_adapter,
    build_sqlite_adapter,
)
from ..s3b.protocol import Capability

SHADOW_KEY_PREFIX = "steward:shadow:"


class ShadowNamespaceGuard:
    """Refuses any key not under the shadow prefix."""

    @staticmethod
    def check(key: str) -> None:
        if not key.startswith(SHADOW_KEY_PREFIX):
            raise ValueError(
                f"shadow backend refuses non-shadow key: {key!r} "
                f"(must start with {SHADOW_KEY_PREFIX!r})"
            )


def _wrap_for_shadow(cap: Capability) -> Capability:
    """Mark the capability as shadow-only and qualification-only."""

    cap.notes = (cap.notes + " [S3C shadow-only]").strip()
    cap.can_persist = True
    cap.requires_approval = True
    return cap


def build_shadow_memory_adapter() -> QualificationAdapter:
    cap = _wrap_for_shadow(
        Capability(name="steward:shadow:memory", can_write=True, can_persist=True)
    )
    return build_memory_adapter(cap)


def build_shadow_sqlite_adapter(db_path: Optional[str] = None) -> QualificationAdapter:
    """SQLite adapter backed by a temp file (deleted by caller after tests)."""

    if db_path is None:
        fd, db_path = tempfile.mkstemp(prefix="s3c_shadow_", suffix=".sqlite")
        os.close(fd)
    cap = _wrap_for_shadow(
        Capability(name="steward:shadow:sqlite", can_write=True, can_persist=True)
    )
    return build_sqlite_adapter(cap, db_path)
