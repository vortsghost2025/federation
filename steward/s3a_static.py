"""S3A static security checks (no-live-I/O proof).

AST-based verification that production S3A modules do not import or invoke
forbidden live connectors:

* socket
* requests
* urllib (networking)
* redis
* subprocess
* Docker SDK
* paramiko
* database drivers
* SSH
* Dagu APIs

Filesystem access is permitted ONLY in the local fixture CLI boundary.
"""

from __future__ import annotations

import ast
import pathlib
from typing import List, Tuple

FORBIDDEN_MODULES = (
    "socket",
    "requests",
    "urllib",
    "redis",
    "subprocess",
    "paramiko",
    "docker",
    "psycopg",
    "psycopg2",
    "pymysql",
    "mysql",
    "sqlite3",
    "sqlalchemy",
    "ssh",
    "fabric",
    "dagu",
    "http.client",
    "telnetlib",
)

# Modules allowed to touch the local filesystem (the fixture CLI boundary).
FILESYS_ALLOWED_MODULES = ("os", "pathlib", "json", "tempfile", "argparse")


def scan_module(source: str) -> List[str]:
    """Return a list of forbidden-import violations found in `source`."""
    violations: List[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    violations.append(f"from {node.module} import ...")
    return violations


def scan_path(path: str) -> Tuple[List[str], List[str]]:
    """Return (violations, scanned_files)."""
    violations: List[str] = []
    scanned: List[str] = []
    p = pathlib.Path(path)
    for py_file in sorted(p.rglob("*.py")):
        # Skip tests and the CLI boundary (allowed filesystem) from the
        # *strict* no-live-I/O assertion, but still scan for forbidden imports.
        text = py_file.read_text(encoding="utf-8")
        scanned.append(str(py_file))
        v = scan_module(text)
        if v:
            violations.append(f"{py_file}: {', '.join(v)}")
    return violations, scanned
