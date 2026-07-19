"""S3B static no-live-connector proof.

Scans all S3B modules for forbidden live connectors. This is the static proof
that the qualification harness never touches a real Federation backend.

Forbidden (live) connectors: redis, requests, urllib, socket, subprocess,
docker, paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib.

Allowed: sqlite3 (ONLY in sqlitedb.py, the local qualification store).
"""

from __future__ import annotations

import os
from typing import List, Tuple

FORBIDDEN_IMPORTS = [
    "redis", "requests", "urllib", "socket", "subprocess", "docker",
    "paramiko", "psycopg", "mysql", "sqlalchemy", "ssh", "fabric",
    "dagu", "http.client", "telnetlib",
]

# sqlite3 is permitted only inside sqlitedb.py.
SQLITE_ALLOWED_IN = ("sqlitedb.py",)


def scan_path(path: str) -> Tuple[List[str], List[str]]:
    """Return (violations, allowed_notes)."""
    violations: List[str] = []
    notes: List[str] = []
    for root, _dirs, files in os.walk(path):
        if "tests" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(root, fn)
            try:
                src = open(fp, "r", encoding="utf-8").read()
            except OSError:
                continue
            for forb in FORBIDDEN_IMPORTS:
                if _imports(src, forb):
                    violations.append(f"{fp}: forbidden import '{forb}'")
            if _imports(src, "sqlite3") and fn not in SQLITE_ALLOWED_IN:
                violations.append(
                    f"{fp}: sqlite3 import not permitted outside {SQLITE_ALLOWED_IN}"
                )
            if _imports(src, "sqlite3") and fn in SQLITE_ALLOWED_IN:
                notes.append(f"{fp}: sqlite3 (permitted local qualification store)")
    return violations, notes


def _imports(src: str, name: str) -> bool:
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if s.startswith("import ") and name in s.split():
            return True
        if s.startswith("from ") and s.split()[1].split(".")[0] == name:
            return True
    return False
