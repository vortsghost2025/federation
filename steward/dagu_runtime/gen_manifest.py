#!/usr/bin/env python3
"""Generate the DR-003 copy manifest for the Steward Dagu runtime.

Walks the `steward` package from the repo root and emits:
  - source_manifest.txt   (human-readable)
  - source_manifest.json  (machine-checkable)

Only files that belong to the offline Steward package are included.
Live/credential/infra artifacts are EXCLUDED by the EXCLUDE rules and
verified absent in security_scan.py (DR-007).
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # .../steward/dagu_runtime -> repo
STEWARD_DIR = REPO_ROOT / "steward"

# Files/dirs never copied into the runtime image (DR-003 exclusion list).
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "drafts", "dagu_runtime"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".so", ".db", ".sqlite", ".sqlite3", ".log",
                    ".tmp", ".bak", ".env", "~")

FORBIDDEN_NAMES = ("npc_agent_current", "credentials", "secret", ".env",
                   "docker-compose", "ssh", "id_rsa", "authorized_keys")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not STEWARD_DIR.is_dir():
        print(f"ERROR: {STEWARD_DIR} not found", file=sys.stderr)
        return 2

    entries = []
    for root, dirs, files in os.walk(STEWARD_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        rel_root = Path(root).relative_to(REPO_ROOT)
        for fn in files:
            p = Path(root) / fn
            if p.suffix in EXCLUDE_SUFFIXES:
                continue
            low = fn.lower()
            if any(b in low for b in FORBIDDEN_NAMES):
                # Surface, do not silently skip forbidden-named files.
                print(f"FORBIDDEN-NAME SKIPPED: {p}", file=sys.stderr)
                continue
            rel = p.relative_to(REPO_ROOT).as_posix()
            digest = sha256_of(p)
            size = p.stat().st_size
            entries.append({"path": rel, "sha256": digest, "bytes": size})

    entries.sort(key=lambda e: e["path"])

    txt_path = Path(__file__).resolve().parent / "source_manifest.txt"
    json_path = Path(__file__).resolve().parent / "source_manifest.json"

    with txt_path.open("w", encoding="utf-8") as fh:
        fh.write("# Steward Dagu Runtime — Source Copy Manifest (DR-003)\n")
        fh.write(f"# generated for fixture_shadow_apply allowlist\n")
        fh.write(f"# repo root: {REPO_ROOT}\n")
        fh.write(f"# total files: {len(entries)}\n")
        fh.write("# format: <sha256>  <bytes>  <relpath>\n")
        for e in entries:
            fh.write(f"{e['sha256']}  {e['bytes']}  {e['path']}\n")

    with json_path.open("w", encoding="utf-8") as fh:
        json.dump({
            "generated_for": "fixture_shadow_apply",
            "repo_root": REPO_ROOT.as_posix(),
            "file_count": len(entries),
            "files": entries,
        }, fh, indent=2)

    print(f"Wrote {len(entries)} entries to {txt_path.name} and {json_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
