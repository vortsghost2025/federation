#!/usr/bin/env python3
"""
Federation verification engine — canonical Python stdlib-only implementation.

Subcommands:
    syntax           Non-mutating AST+compile validation (no __pycache__)
    discover-static  AST-based static test inventory (no pytest)
    collect          Pytest collection (explicit opt-in; NOT in "all")
    tests-isolated   Run only explicit allowlisted test node IDs
    frontend         Node.js --check if available
    all              Default-safe checks: syntax + discover-static + frontend
    help             This message

Result states: PASS, FAIL, NOT_RUN, UNAVAILABLE
Exit codes:
    0  all requested checks PASS (or NOT_RUN)
    1  one or more FAIL or required checker UNAVAILABLE
    2  usage error (invalid command/argument)
    3  internal engine error (unexpected exception)

Repository paths are resolved from the script location:
    scripts/verify.py lives under <repo-root>/scripts
    repository root is the parent of scripts
    Federation game root is <repo-root>/federation-game

An optional --repo-root argument overrides repository resolution.

Artifact paths:
    Windows: %LOCALAPPDATA%/Federation/verify/<timestamp>/
        (falls back to <user-home>/.local/share/Federation/verify if LOCALAPPDATA unset)
    Linux:   $XDG_STATE_HOME/Federation/verify/<timestamp>/
        (falls back to ~/.local/state/Federation/verify if XDG_STATE_HOME unset)

No automatic deletion of prior runs. All prior evidence and verification
runs are preserved. Retention policy is future work only.

No Redis, PostgreSQL, providers, Ollama, VPS contact in default commands.
fed-state.sh is prohibited as an operational tool.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path resolution — from script location, not hardcoded
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent


def _resolve_repo_root() -> Path:
    if "--repo-root" in sys.argv:
        idx = sys.argv.index("--repo-root")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1]).resolve()
    return SCRIPT_DIR.parent


def _resolve_game_root_for(repo: Path) -> Path:
    nested = repo / "federation-game"
    if nested.exists() and (nested / "backend").is_dir():
        return nested
    # VPS case: the script lives under /docker/federation-game/scripts,
    # so the repo root IS the game root.
    return repo


def _resolve_game_root() -> Path:
    return _resolve_game_root_for(_resolve_repo_root())


def _resolve_artifact_root() -> Path:
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        xdg = os.environ.get("XDG_STATE_HOME")
        if xdg:
            return Path(xdg) / "Federation" / "verify"
        return Path.home() / ".local" / "state" / "Federation" / "verify"
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        return Path(local_app) / "Federation" / "verify"
    return Path.home() / ".local" / "share" / "Federation" / "verify"


REPO_ROOT = _resolve_repo_root()
GAME_ROOT = _resolve_game_root()
ARTIFACT_ROOT = _resolve_artifact_root()

# ---------------------------------------------------------------------------
# Project subdirectories (resolved from GAME_ROOT)
# ---------------------------------------------------------------------------

PROJECT_DIRS: dict[str, Path] = {
    "backend": GAME_ROOT / "backend",
    "tests": GAME_ROOT / "tests",
    "npc_agent": GAME_ROOT / "npc-agent",
    "frontend": GAME_ROOT / "frontend",
    "routes": GAME_ROOT / "backend" / "routes",
}

# Patterns matching non-active helper/historical/alternate files to exclude
# from the default `syntax` and `all` commands. These are checked against
# the filename (lowercased).
_EXCLUDE_SYNTAX_PATTERNS = (
    re.compile(r"^.*_vps\.py$"),
    re.compile(r"^fix.*\.py$"),
    re.compile(r"^.*_fix\.py$"),
    re.compile(r"^kilo.*_fix.*\.py$"),
    re.compile(r"^strip_duplicates\.py$"),
    re.compile(r"^check_.*\.py$"),
    re.compile(r"^smoke.*\.py$"),
    re.compile(r"^manual.*\.py$"),
    re.compile(r"^vps_test\.py$"),
    re.compile(r"^test_.*\.py$"),
    re.compile(r"^.*_test\.py$"),
    re.compile(r"^_find_.*\.py$"),
    re.compile(r"^_fix_.*\.py$"),
    re.compile(r"^_strip_.*\.py$"),
)

# Human-readable reason for each exclusion pattern (for logging)
_EXCLUDE_REASONS = {
    r"^.*_vps\.py$": "non-active VPS helper",
    r"^fix.*\.py$": "fix script",
    r"^.*_fix\.py$": "fix script",
    r"^kilo.*_fix.*\.py$": "kilo fix script",
    r"^strip_duplicates\.py$": "dedup helper",
    r"^check_.*\.py$": "check script",
    r"^smoke.*\.py$": "smoke test",
    r"^manual.*\.py$": "manual test",
    r"^vps_test\.py$": "VPS test",
    r"^test_.*\.py$": "test module",
    r"^.*_test\.py$": "test module",
    r"^_find_.*\.py$": "find helper",
    r"^_fix_.*\.py$": "fix helper",
    r"^_strip_.*\.py$": "strip helper",
}


def _is_active_python(name: str) -> bool:
    """Return False if the filename matches a non-active helper/historical pattern."""
    nl = name.lower()
    for pat in _EXCLUDE_SYNTAX_PATTERNS:
        if pat.match(nl):
            return False
    return True


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECT_ACK_FLAG = "I_UNDERSTAND_COLLECT_INVOKES_PYTEST"

SANITIZED_ENV_VARS = [
    "DATABASE_URL", "REDIS_URL", "REDIS_HOST", "REDIS_PORT",
    "NIM_API_KEYS", "NIM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "VPS_HOST", "VPS_IP", "VPS_USER", "VPS_SSH_KEY",
    "POSTGRES_PASSWORD", "POSTGRES_USER", "PGPASSWORD",
    "OLLAMA_HOST", "OLLAMA_BASE_URL",
    "TAVILY_API_KEY", "EXA_API_KEY",
    "FEDERATION_API_KEY", "FEDERATION_SECRET",
]

REVIEW_SIGNAL_FILENAME_TOKENS = (
    "nim", "provider", "ollama", "vps", "live",
    "route", "tick", "agent", "smoke", "integration",
)

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Result + Verifier
# ---------------------------------------------------------------------------


class Result:
    def __init__(self, check: str, label: str, state: str, detail: str = ""):
        self.check = check
        self.label = label
        self.state = state
        self.detail = detail

    def to_dict(self) -> dict:
        return {"check": self.check, "label": self.label, "state": self.state, "detail": self.detail}


class Verifier:
    def __init__(self, mode: str = "strict", changed_only: bool = False):
        self.mode = mode
        self.changed_only = changed_only
        self.results: list[Result] = []
        self.artifact_dir = self._mkdir()
        self.lines: list[str] = []
        self.t0 = time.time()
        self._log("=== Federation Verification Engine ===")
        self._log(f"Repository root: {REPO_ROOT}")
        self._log(f"Federation game root: {GAME_ROOT}")
        self._log(f"Artifact root: {ARTIFACT_ROOT}")
        self._log(f"Mode: {self.mode}")
        self._log(f"Artifacts (this run): {self.artifact_dir}")
        self._log(f"Timestamp: {utc_iso()}")
        self._log("Automatic deletion: DISABLED (all prior runs preserved)")

    def _mkdir(self) -> Path:
        d: Path = ARTIFACT_ROOT / utc_ts()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.lines.append(line)
        print(line, flush=True)

    def _add(self, check: str, target: str, status: str, detail: str = "") -> None:
        r = Result(check, target, status, detail)
        self.results.append(r)
        tag = {"PASS": "OK", "FAIL": "FAIL", "NOT_RUN": "SKIP", "UNAVAILABLE": "UNAV"}[status]
        self._log(f"  [{tag}] {check}: {target} {detail}")

    def _flush(self) -> None:
        out = self.artifact_dir / "result.json"
        summary = {
            "ts": utc_iso(),
            "mode": self.mode,
            "repository_root": str(REPO_ROOT),
            "game_root": str(GAME_ROOT),
            "artifact_root": str(ARTIFACT_ROOT),
            "n": len(self.results),
            "pass": sum(1 for r in self.results if r.state == "PASS"),
            "fail": sum(1 for r in self.results if r.state == "FAIL"),
            "skip": sum(1 for r in self.results if r.state == "NOT_RUN"),
            "unav": sum(1 for r in self.results if r.state == "UNAVAILABLE"),
            "s": round(time.time() - self.t0, 2),
            "results": [r.to_dict() for r in self.results],
        }
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        log_file = self.artifact_dir / "verify.log"
        log_file.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def exit_code(self) -> int:
        if any(r.state == "FAIL" for r in self.results):
            return 1
        if self.mode == "strict" and any(r.state == "UNAVAILABLE" for r in self.results):
            return 1
        return 0

    # ═══════════════════ SYNTAX ════════════════════════════════════
    @staticmethod
    def _check_one(fp: Path) -> Result:
        try:
            src = fp.read_text(encoding="utf-8")
            ast.parse(src, filename=str(fp))
            compile(src, str(fp), "exec")
            return Result("syntax", str(fp), "PASS")
        except SyntaxError as e:
            return Result("syntax", str(fp), "FAIL", f"L{e.lineno}: {e.msg}")
        except Exception as e:
            return Result("syntax", str(fp), "FAIL", str(e))

    def _py_globs(self, d: Path) -> list[Path]:
        if not d.exists():
            return []
        return sorted(f for f in d.glob("*.py") if f.is_file() and not _bad_name(f.name))

    def _excluded_reason(self, name: str) -> str | None:
        """Return a human-readable reason string if the file is excluded from
        active scope, or None if it is active."""
        for pat_str, reason in _EXCLUDE_REASONS.items():
            if re.match(pat_str, name, re.IGNORECASE):
                return reason
        return None

    def _collect_active_files(self) -> tuple[list[Path], list[tuple[str, str]]]:
        """Collect active-runtime Python files. Returns (included, excluded_with_reasons)."""
        files: list[Path] = []
        for k in ("backend", "routes", "npc_agent"):
            if k in PROJECT_DIRS:
                files.extend(self._py_globs(PROJECT_DIRS[k]))
        # Include alembic env source only at top level
        alembic_dir = PROJECT_DIRS.get("backend", Path()) / "alembic"
        if alembic_dir.exists():
            files.append(alembic_dir / "env.py")
            versions_dir = alembic_dir / "versions"
            if versions_dir.exists():
                files.extend(sorted(f for f in versions_dir.glob("*.py") if f.is_file() and not _bad_name(f.name)))
        included: list[Path] = []
        excluded: list[tuple[str, str]] = []
        for f in sorted(set(files)):
            reason = self._excluded_reason(f.name)
            if reason:
                excluded.append((str(f), reason))
            else:
                included.append(f)
        return included, excluded

    def run_syntax(self, paths: list[str] | None = None) -> None:
        self._log("--- syntax (active runtime scope) ---")
        if paths:
            files = [Path(p) for p in paths if Path(p).exists()]
            excluded = []
        elif self.changed_only:
            files = self._git_changed()
            excluded = []
        else:
            files, excluded = self._collect_active_files()
            self._log(f"  Excluded {len(excluded)} non-active candidate(s):")
            for fp, reason in excluded:
                self._log(f"    [EXCLUDED] {fp} — {reason}")
        if not files:
            self._add("syntax", "none", "NOT_RUN", "no files")
            return
        for ff in sorted(set(files)):
            r = self._check_one(ff)
            self._add(r.check, r.label, r.state, r.detail)

    def run_syntax_broad(self, paths: list[str] | None = None) -> None:
        """Check ALL bounded Python candidates including historical/helpers.
        Use --paths for explicit files."""
        self._log("--- syntax-broad (all candidates) ---")
        files = []
        for k in ("backend", "routes"):
            files.extend(self._py_globs(PROJECT_DIRS[k]))
        for pr in ("backend",):
            alembic_dir = PROJECT_DIRS[pr] / "alembic"
            if alembic_dir.exists():
                files.append(alembic_dir / "env.py")
            alembic_versions = PROJECT_DIRS[pr] / "alembic" / "versions"
            if alembic_versions.exists():
                files.extend(sorted(f for f in alembic_versions.glob("*.py") if f.is_file() and not _bad_name(f.name)))
        if paths:
            files = [Path(p) for p in paths if Path(p).exists()]
        if not files:
            self._add("syntax-broad", "none", "NOT_RUN", "no files")
            return
        excluded_names: list[str] = []
        for ff in sorted(set(files)):
            if not _is_active_python(ff.name):
                excluded_names.append(ff.name)
            r = self._check_one(ff)
            self._add("syntax-broad", str(ff), r.state, r.detail)
        if excluded_names:
            self._log(f"  Non-active candidates included (not excluded from broad): {len(excluded_names)}")

    # ═══════════════════ FRONTEND ══════════════════════════════════
    def _frontend_dir(self) -> Path:
        """Return the served frontend directory (public_html) if present,
        otherwise the frontend/ source directory."""
        public_html = GAME_ROOT / "public_html"
        if public_html.exists() and public_html.is_dir():
            return public_html
        return PROJECT_DIRS["frontend"]

    def _node_version(self) -> tuple[str | None, str | None]:
        """Return (node_executable, version_string) or (None, None)."""
        try:
            r = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ver = r.stdout.strip()
                return "node", ver
        except Exception:
            pass
        try:
            r = subprocess.run(["nodejs", "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ver = r.stdout.strip()
                return "nodejs", ver
        except Exception:
            pass
        return None, None

    def run_frontend(self) -> None:
        """Default frontend check: validates the SERVED public_html JavaScript."""
        self._log("--- frontend (served public_html) ---")
        nd, nver = self._node_version()
        if not nd:
            self._add("frontend", "node", "UNAVAILABLE", "Node.js not found")
            return
        if nver:
            self._log(f"  Node version: {nver}")
        fe = self._frontend_dir()
        candidates: list[Path] = sorted(f for f in fe.glob("*.js") if f.is_file())
        if not candidates:
            self._add("frontend", "none", "NOT_RUN", "no js files in served dir")
            return
        self._log(f"  Checking served directory: {fe}")
        for f in sorted(candidates):
            rv = subprocess.run([nd, "--check", str(f)], capture_output=True, text=True, timeout=15)
            if rv.returncode == 0:
                self._add("frontend", str(f), "PASS")
            else:
                stderr = rv.stderr or ""
                if _is_modern_js_error(stderr):
                    self._add("frontend", str(f), "UNAVAILABLE",
                              f"NODE_PARSER_TOO_OLD (Node {nver or '?'} cannot parse modern syntax)")
                else:
                    self._add("frontend", str(f), "FAIL",
                              (stderr or f"exit {rv.returncode}")[:200])

    def run_frontend_source(self) -> None:
        """Explicit frontend source check: validates federation-game/frontend JavaScript."""
        self._log("--- frontend-source (frontend/) ---")
        nd, nver = self._node_version()
        if not nd:
            self._add("frontend-source", "node", "UNAVAILABLE", "Node.js not found")
            return
        if nver:
            self._log(f"  Node version: {nver}")
        fe = PROJECT_DIRS["frontend"]
        candidates: list[Path] = sorted(f for f in fe.glob("*.js") if f.is_file())
        if not candidates:
            self._add("frontend-source", "none", "NOT_RUN", "no js files in frontend/ source")
            return
        self._log(f"  Checking source directory: {fe}")
        for f in sorted(candidates):
            rv = subprocess.run([nd, "--check", str(f)], capture_output=True, text=True, timeout=15)
            if rv.returncode == 0:
                self._add("frontend-source", str(f), "PASS")
            else:
                stderr = rv.stderr or ""
                if _is_modern_js_error(stderr):
                    self._add("frontend-source", str(f), "UNAVAILABLE",
                              f"NODE_PARSER_TOO_OLD (Node {nver or '?'} cannot parse modern syntax)")
                else:
                    self._add("frontend-source", str(f), "FAIL",
                              (stderr or f"exit {rv.returncode}")[:200])

    # ═══════════════════ DISCOVER-STATIC ═══════════════════════════
    def run_discover_static(self) -> None:
        self._log("--- discover-static ---")
        inv: list[dict] = []
        for label, bp in PROJECT_DIRS.items():
            if not bp.exists():
                continue
            # For frontend, skip — no Python tests there
            if label == "frontend":
                continue
            for tf in sorted(bp.glob("test_*.py")):
                if _bad_name(tf.name):
                    continue
                # genesis path tests are unknown until investigated
                if "genesis" in str(tf):
                    entry = _scan_test(tf)
                    entry["classification"] = "UNKNOWN"
                    entry["reason"] = "genesis path — not reviewed"
                    entry["review_status"] = "PENDING"
                    inv.append(entry)
                    self._add("discover", str(tf), "PASS", "class=UNKNOWN review=PENDING")
                    continue
                entry = _scan_test(tf)
                inv.append(entry)
                self._add("discover", str(tf), "PASS", f"class={entry['classification']} review={entry['review_status']}")

        fp = self.artifact_dir / "test-inventory.json"
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(inv, f, indent=2, ensure_ascii=False)
        self._log(f"Inventory: {len(inv)} modules -> {fp}")
        counts: dict[str, int] = {}
        review_counts: dict[str, int] = {}
        for m in inv:
            c = m["classification"]
            counts[c] = counts.get(c, 0) + 1
            r = m["review_status"]
            review_counts[r] = review_counts.get(r, 0) + 1
        for c, n in sorted(counts.items()):
            self._log(f"  classification {c}: {n}")
        for r, n in sorted(review_counts.items()):
            self._log(f"  review_status {r}: {n}")
        self._log("  ALLOWLIST STATUS: NOT_APPROVED (no node IDs approved)")

    # ═══════════════════ COLLECT ═══════════════════════════════════
    def run_collect(self, ack: str | None, timeout: int) -> None:
        self._log("--- collect ---")
        if ack != COLLECT_ACK_FLAG:
            self._add("collect", "ack", "FAIL",
                      f"refused: requires --ack {COLLECT_ACK_FLAG}")
            return
        # Refuse if static discovery has unresolved conftest conditions
        # (here: presence of genesis conftest marks unresolved risk)
        conftest = PROJECT_DIRS["backend"] / "genesis" / "tests" / "conftest.py"
        if conftest.exists():
            self._add("collect", "conftest", "FAIL",
                      "unresolved conftest at backend/genesis/tests/conftest.py — refusal")
            return
        if not _has_pytest():
            self._add("collect", "pytest", "UNAVAILABLE", "pytest not installed")
            return
        env = _sanitized_env()
        cmd = [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider",
               "-q", str(GAME_ROOT)]
        try:
            rv = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
            if rv.returncode == 0:
                self._add("collect", "pytest", "PASS", f"collected ({len(rv.stdout.splitlines())} lines)")
            else:
                self._add("collect", "pytest", "FAIL",
                          (rv.stderr or rv.stdout or f"exit {rv.returncode}")[:300])
        except subprocess.TimeoutExpired:
            self._add("collect", "pytest", "FAIL", f"timeout after {timeout}s")
        except Exception as e:
            self._add("collect", "pytest", "FAIL", f"error: {e}")

    # ═══════════════════ TESTS-ISOLATED ════════════════════════════
    def run_tests_isolated(self, allowlist_path: str | None,
                            inventory_path: str | None,
                            timeout: int) -> None:
        self._log("--- tests-isolated ---")
        if not allowlist_path:
            self._add("tests-isolated", "allowlist", "FAIL",
                      "refused: requires --allowlist PATH")
            return
        ap = Path(allowlist_path)
        if not ap.exists():
            self._add("tests-isolated", "allowlist", "FAIL", "allowlist file not found")
            return
        try:
            raw = ap.read_text(encoding="utf-8")
            if not raw.strip():
                self._add("tests-isolated", "allowlist", "FAIL", "allowlist is empty")
                return
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self._add("tests-isolated", "allowlist", "FAIL", f"malformed JSON: {e}")
            return
        if not isinstance(data, dict):
            self._add("tests-isolated", "allowlist", "FAIL", "allowlist root is not an object")
            return
        status = data.get("status", "")
        if status != "APPROVED":
            self._add("tests-isolated", "allowlist", "FAIL",
                      f"allowlist status is {status!r}; must be 'APPROVED'")
            return
        node_ids = data.get("node_ids", [])
        if not isinstance(node_ids, list) or not node_ids:
            self._add("tests-isolated", "allowlist", "FAIL", "node_ids missing or empty")
            return
        # Reject wildcards and keyword expressions
        for nid in node_ids:
            if not isinstance(nid, str) or not nid:
                self._add("tests-isolated", "allowlist", "FAIL",
                          f"invalid node id: {nid!r}")
                return
            if any(ch in nid for ch in ("*", "?", "[")):
                self._add("tests-isolated", "allowlist", "FAIL",
                          f"wildcard in node id: {nid!r}")
                return
            if " or " in nid or " and " in nid or " not " in nid:
                self._add("tests-isolated", "allowlist", "FAIL",
                          f"keyword expression in node id: {nid!r}")
                return
        # Inventory path / digest check
        if inventory_path:
            ip = Path(inventory_path)
            if not ip.exists():
                self._add("tests-isolated", "inventory", "FAIL", "inventory file not found")
                return
            inv_digest = data.get("inventory_sha256")
            if inv_digest:
                actual = hashlib.sha256(ip.read_bytes()).hexdigest()
                if actual != inv_digest:
                    self._add("tests-isolated", "inventory", "FAIL",
                              "inventory digest mismatch (allowlist stale)")
                    return
        else:
            self._add("tests-isolated", "inventory", "NOT_RUN",
                      "no inventory path provided — digest not checked")

        if not _has_pytest():
            self._add("tests-isolated", "pytest", "UNAVAILABLE", "pytest not installed")
            return

        env = _sanitized_env()
        tmpdir = tempfile.mkdtemp(prefix="fed-verify-")
        try:
            cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                   "--rootdir", tmpdir, "-q"] + node_ids
            try:
                rv = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=timeout, env=env, cwd=tmpdir)
                if rv.returncode == 0:
                    self._add("tests-isolated", "pytest", "PASS",
                              f"{len(node_ids)} node(s) executed")
                else:
                    self._add("tests-isolated", "pytest", "FAIL",
                              (rv.stderr or rv.stdout or f"exit {rv.returncode}")[:300])
            except subprocess.TimeoutExpired:
                self._add("tests-isolated", "pytest", "FAIL", f"timeout after {timeout}s")
            except Exception as e:
                self._add("tests-isolated", "pytest", "FAIL", f"error: {e}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ═══════════════════ ALL ═══════════════════════════════════════
    def run_all(self) -> None:
        self.run_syntax()
        self.run_discover_static()
        self.run_frontend()
        self._log(f"Done. ({time.time() - self.t0:.1f}s)")

    # ═══════════════════ HELPERS ═══════════════════════════════════
    def _git_changed(self) -> list[Path]:
        try:
            r = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                               capture_output=True, text=True, timeout=10, cwd=str(REPO_ROOT))
            return [REPO_ROOT / line for line in r.stdout.strip().split("\n") if line]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _bad_name(name: str) -> bool:
    nl = name.lower()
    for p in (".bak", "backup", ".orig", ".new", "__pycache__", ".pyc",
              "_current.py", ".orig.py"):
        if p in nl:
            return True
    return False


def _is_active_python(name: str) -> bool:
    """Return False if the filename matches a non-active helper/historical pattern."""
    nl = name.lower()
    for pat in _EXCLUDE_SYNTAX_PATTERNS:
        if pat.match(nl):
            return False
    return True


def _is_modern_js_error(stderr: str) -> bool:
    """Detect whether a Node.js parser error is due to modern syntax the parser
    cannot understand (optional chaining, nullish coalescing, top-level await)."""
    text = stderr.lower()
    modern_tokens = [
        "unexpected token '?'",       # optional chaining ?. or nullish coalescing ??
        "unexpected token '.'",       # optional chaining ?.
        "unexpected token ','",       # sometimes from nullish coalescing
    ]
    for tok in modern_tokens:
        if tok in text:
            return True
    return False


def _has_pytest() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _sanitized_env() -> dict[str, str]:
    env = dict(os.environ)
    for v in SANITIZED_ENV_VARS:
        env.pop(v, None)
    # Also strip anything that looks like a credential
    for k in list(env.keys()):
        kl = k.lower()
        if any(tok in kl for tok in ("key", "token", "secret", "password", "api_key")):
            env.pop(k, None)
    return env


# ---------------------------------------------------------------------------
# Static test inventory — conservative scan
# ---------------------------------------------------------------------------

APP_MODULE_HINTS = {
    "llm_router", "nvidia_nim_client", "state", "federation_game_db",
    "npc_autonomy", "institutions", "npcs", "npc_agent", "npc_actions",
    "npc_redis_helpers", "simulation_engine", "simulation_operator",
    "operator_auth", "tick_engine", "tick_watchdog", "worker",
    "faction_ai", "faction_dynamics", "faction_diplomacy",
    "federation_game_console", "federation_game_events",
    "federation_game_npcs", "federation_game_state", "federation_game_turns",
    "map_endpoints", "narrator", "quests", "spatial_state", "technology",
    "timeline", "councilor_bridge", "event_cascade",
    "autonomous_choice_resolver", "npc_chat", "npc_cognition",
    "npc_memory", "npc_quest_engine", "npc_world_snapshot",
    "npc_artifacts", "npc_event_log", "npc_activity_logger",
    "npc_goals", "npc_messaging", "spatial_models", "spatial_queries",
    "spatial_seed", "state_constants", "state_helpers",
}


def _scan_test(fpath: Path) -> dict:
    """Build a conservative static-inventory record for a single test module."""
    rel = str(fpath)
    functions: list[str] = []
    classes: list[str] = []
    imports: list[str] = []
    from_imports: list[str] = []
    decorators: list[str] = []
    local_fixtures: list[str] = []
    fixture_refs: list[str] = []
    module_calls: list[str] = []
    module_obj_constructs: list[str] = []
    subprocess_indicators: list[str] = []
    fs_write_indicators: list[str] = []
    network_indicators: list[str] = []
    redis_indicators: list[str] = []
    sql_indicators: list[str] = []
    provider_indicators: list[str] = []
    ollama_indicators: list[str] = []
    ssh_indicators: list[str] = []
    env_var_reads: list[str] = []
    app_module_imports: list[str] = []
    conftest_paths: list[str] = []

    reasons: list[str] = []

    try:
        src = fpath.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(fpath))
    except SyntaxError as e:
        return {
            "file": rel, "functions": [], "classes": [], "imports": [],
            "from_imports": [], "decorators": [], "local_fixtures": [],
            "fixture_refs": [], "conftest_paths": [], "module_calls": [],
            "module_obj_constructs": [], "subprocess_indicators": [],
            "fs_write_indicators": [], "network_indicators": [],
            "redis_indicators": [], "sql_indicators": [],
            "provider_indicators": [], "ollama_indicators": [],
            "ssh_indicators": [], "env_var_reads": [],
            "app_module_imports": [], "unresolved_transitive_import_risk": True,
            "classification": "UNKNOWN", "reasons": [f"syntax error: {e}"],
            "review_status": "PENDING",
        }
    except Exception as e:
        return {
            "file": rel, "functions": [], "classes": [], "imports": [],
            "from_imports": [], "decorators": [], "local_fixtures": [],
            "fixture_refs": [], "conftest_paths": [], "module_calls": [],
            "module_obj_constructs": [], "subprocess_indicators": [],
            "fs_write_indicators": [], "network_indicators": [],
            "redis_indicators": [], "sql_indicators": [],
            "provider_indicators": [], "ollama_indicators": [],
            "ssh_indicators": [], "env_var_reads": [],
            "app_module_imports": [], "unresolved_transitive_import_risk": True,
            "classification": "UNKNOWN", "reasons": [f"parse error: {e}"],
            "review_status": "PENDING",
        }

    # Collect conftest candidates (same dir + parent dirs up to game root)
    parent = fpath.parent
    while parent >= GAME_ROOT:
        cf = parent / "conftest.py"
        if cf.exists():
            conftest_paths.append(str(cf))
        if parent == GAME_ROOT:
            break
        parent = parent.parent

    # Walk AST
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("test"):
                functions.append(node.name)
            elif node.name == "fixture":
                local_fixtures.append(node.name)
            # decorators
            for dec in node.decorator_list:
                dname = _decorator_name(dec)
                if dname:
                    decorators.append(dname)
                    if dname in ("fixture", "pytest.fixture"):
                        local_fixtures.append(node.name)
        elif isinstance(node, ast.ClassDef):
            if any(isinstance(b, ast.FunctionDef) and b.name.startswith("test") for b in node.body):
                classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                from_imports.append(mod)
        elif isinstance(node, ast.Call):
            fname = _call_name(node.func)
            if fname:
                module_calls.append(fname)
                # subprocess indicators
                if any(tok in fname for tok in ("subprocess", "Popen", "run", "check_output",
                                                  "check_call", "system")):
                    subprocess_indicators.append(fname)
                # fs write indicators
                if any(tok in fname for tok in ("open", "write", "writelines", "mkdir",
                                                  "makedirs", "unlink", "remove", "rmdir")):
                    fs_write_indicators.append(fname)
                # network
                if any(tok in fname for tok in ("requests.get", "requests.post",
                                                  "socket", "urlopen", "httpx")):
                    network_indicators.append(fname)
                # redis
                if "redis" in fname.lower():
                    redis_indicators.append(fname)
                # sql — only when a specific db framework call is detected;
                # .execute_decision() (an app function) must not match.
                if any(tok in fname for tok in ("cursor.execute", "connection.execute",
                                                  "session.execute", "engine.execute",
                                                  "psycopg2", "sqlalchemy", "create_engine")):
                    sql_indicators.append(fname)
        elif isinstance(node, ast.Attribute):
            aname = _attr_chain(node)
            if aname:
                if any(tok in aname for tok in ("os.environ", "os.getenv")):
                    env_var_reads.append(aname)
                if "redis" in aname.lower():
                    redis_indicators.append(aname)
                if any(tok in aname for tok in ("openai", "nvidia_nim", "nim.", "anthropic")):
                    provider_indicators.append(aname)
                if "ollama" in aname.lower():
                    ollama_indicators.append(aname)
                if any(tok in aname for tok in ("paramiko", "ssh")):
                    ssh_indicators.append(aname)

    # Also check raw source for textual indicators
    src_lower = src.lower()
    if "import requests" in src or "from requests" in src:
        network_indicators.append("requests import")
    if "import httpx" in src or "from httpx" in src:
        network_indicators.append("httpx import")
    if "import urllib" in src or "from urllib" in src:
        network_indicators.append("urllib import")
    if "import socket" in src or "from socket" in src:
        network_indicators.append("socket import")
    if "redis" in src_lower:
        redis_indicators.append("redis mention")
    if any(tok in src_lower for tok in ("psycopg2", "sqlalchemy", "asyncpg", "create_engine",
                                         "sessionmaker")):
        sql_indicators.append("sql/db reference")
    if any(tok in src_lower for tok in ("openai", "nvidia_nim", "nim_api", "anthropic",
                                         "nim_base_url")):
        provider_indicators.append("provider reference")
    if "ollama" in src_lower:
        ollama_indicators.append("ollama reference")
    if any(tok in src_lower for tok in ("paramiko", "ssh", "fabric", "scp")):
        ssh_indicators.append("ssh/vps reference")
    if "os.environ" in src or "os.getenv" in src:
        env_var_reads.append("os.environ/getenv")
    if "subprocess" in src_lower:
        subprocess_indicators.append("subprocess reference")

    # Resolve app-module imports
    for imp in imports + from_imports:
        root = imp.split(".")[0]
        if root in APP_MODULE_HINTS:
            app_module_imports.append(imp)

    # Build probable node IDs
    probable_node_ids: list[str] = []
    for fn in functions:
        probable_node_ids.append(f"{fpath.name}::{fn}")
    for cls in classes:
        probable_node_ids.append(f"{fpath.name}::{cls}")

    unresolved_transitive = bool(app_module_imports)

    # Conservative classification
    classification = "UNKNOWN"
    review_status = "PENDING"

    # Filename review signal
    fname_lower = fpath.name.lower()
    filename_review_signal = any(tok in fname_lower for tok in REVIEW_SIGNAL_FILENAME_TOKENS)

    if redis_indicators:
        classification = "REDIS_DEPENDENT"
        reasons.append("redis indicators detected")
    if sql_indicators:
        classification = "DATABASE_DEPENDENT"
        reasons.append("database/SQL indicators detected")
    if provider_indicators:
        classification = "PROVIDER_DEPENDENT"
        reasons.append("provider/NIM/OpenAI indicators detected")
    if ollama_indicators:
        classification = "OLLAMA_DEPENDENT"
        reasons.append("ollama indicators detected")
    if ssh_indicators:
        classification = "VPS_DEPENDENT"
        reasons.append("ssh/vps indicators detected")
    if network_indicators:
        classification = "VPS_DEPENDENT"
        reasons.append("network/HTTP/socket indicators detected — likely live routes")
    if subprocess_indicators or fs_write_indicators:
        if classification == "UNKNOWN":
            classification = "MUTATION_CAPABLE"
        reasons.append("subprocess or filesystem-write indicators detected")

    # If app-module imports exist and classification is still UNKNOWN,
    # do NOT promote to ISOLATED_CANDIDATE — keep UNKNOWN per the rules.
    if classification == "UNKNOWN":
        if app_module_imports:
            classification = "UNKNOWN"
            reasons.append("application-module imports present; transitive review incomplete")
        elif not functions and not classes:
            classification = "UNKNOWN"
            reasons.append("no statically-discoverable test functions or classes")
        else:
            # No app imports, no service indicators — still UNKNOWN pending review
            classification = "UNKNOWN"
            reasons.append("no service indicators but source review not completed")

    # Filename review signal overrides isolation
    if filename_review_signal and classification == "ISOLATED_CANDIDATE":
        classification = "UNKNOWN"
        reasons.append(f"filename contains review signal token; downgraded from ISOLATED_CANDIDATE")

    # Per the spec, never auto-classify as ISOLATED_CANDIDATE — everything stays UNKNOWN
    # until a complete source review is actually recorded.
    if classification == "ISOLATED_CANDIDATE":
        classification = "UNKNOWN"
        reasons.append("automatic ISOLATED_CANDIDATE disabled; pending source review")

    return {
        "file": rel,
        "functions": sorted(set(functions)),
        "classes": sorted(set(classes)),
        "probable_node_ids": sorted(set(probable_node_ids)),
        "imports": sorted(set(imports)),
        "from_imports": sorted(set(from_imports)),
        "decorators": sorted(set(decorators)),
        "local_fixtures": sorted(set(local_fixtures)),
        "fixture_refs": sorted(set(fixture_refs)),
        "conftest_paths": sorted(set(conftest_paths)),
        "module_calls": sorted(set(module_calls)),
        "module_obj_constructs": sorted(set(module_obj_constructs)),
        "subprocess_indicators": sorted(set(subprocess_indicators)),
        "fs_write_indicators": sorted(set(fs_write_indicators)),
        "network_indicators": sorted(set(network_indicators)),
        "redis_indicators": sorted(set(redis_indicators)),
        "sql_indicators": sorted(set(sql_indicators)),
        "provider_indicators": sorted(set(provider_indicators)),
        "ollama_indicators": sorted(set(ollama_indicators)),
        "ssh_indicators": sorted(set(ssh_indicators)),
        "env_var_reads": sorted(set(env_var_reads)),
        "app_module_imports": sorted(set(app_module_imports)),
        "unresolved_transitive_import_risk": unresolved_transitive,
        "classification": classification,
        "reasons": reasons or ["no specific indicators; defaults to UNKNOWN pending review"],
        "review_status": review_status,
    }


def _decorator_name(dec) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return _attr_chain(dec) or ""
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ""


def _attr_chain(node) -> str:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _call_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attr_chain(node) or ""
    return ""


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP_TEXT = r"""
Federation Verification Engine — canonical cross-platform verification.

USAGE:
  python scripts/verify.py <command> [options]

COMMANDS:
  syntax [--paths FILE...] [--changed]
      Check Python syntax via ast.parse + compile (no import, no __pycache__).
      Defaults to active backend + routes + alembic sources.

  discover-static
      Build a conservative static test inventory via AST only (no pytest).
      Every entry starts with review_status=PENDING.
      Output: test-inventory.json in the artifact directory.

  collect --ack I_UNDERSTAND_COLLECT_INVOKES_PYTEST [--timeout SECONDS]
      Run pytest --collect-only with cache disabled and a bounded timeout.
      Explicit opt-in only — NOT included in "all".
      Refuses when an unresolved conftest condition is detected.
      Uses a sanitized child environment (no credential variables).

  tests-isolated --allowlist PATH [--inventory PATH] [--timeout SECONDS]
      Run only exact pytest node IDs listed in an APPROVED allowlist JSON.
      Requires an external allowlist with status="APPROVED".
      Refuses missing, empty, malformed, stale, or unreviewed allowlists.
      Accepts exact node IDs only — rejects wildcards and keyword expressions.
      Disables pytest cache, uses bounded timeout, sanitized child env,
      disposable temporary working directory.
      NOT included in "all".
      No allowlist is created or approved by this engine.

  frontend [--changed]
      Run node --check on active JavaScript files (served public_html/).
      UNAVAILABLE if Node missing or parser too old (modern JS unsupported).

  frontend-source [--changed]
      Run node --check on frontend/ source JavaScript files.
      UNAVAILABLE if Node missing or parser too old.

  syntax-broad [--paths FILE...] [--changed]
      Like syntax, but does NOT filter out helper/fix scripts.
      Catches syntax errors in all *.py candidates found.

  all
      Default-safe checks only: syntax + discover-static + frontend.
      Does NOT invoke pytest, execute tests, contact the VPS, or contact
      Redis, PostgreSQL, providers, Ollama, or external services.

  help
      This message.

EXIT CODES:
  0  all requested checks PASS (or NOT_RUN)
  1  one or more FAIL or required checker UNAVAILABLE
  2  usage error (invalid command/argument)
  3  internal engine error (unexpected exception)

ARTIFACT LOCATION:
  Windows: %LOCALAPPDATA%\Federation\verify\<timestamp>\
  Linux:   $XDG_STATE_HOME/Federation\verify\<timestamp>\
           (or ~/.local/state/Federation/verify/<timestamp>/)

  Contains: result.json, test-inventory.json, verify.log

RULES — READ BEFORE RUNNING:
  - No dependency installation.
  - No live-service, Redis, PostgreSQL, VPS, or provider access in default mode.
  - No automatic deletion of prior runs.
  - fed-state.sh is prohibited as an operational tool.
"""


# ---------------------------------------------------------------------------
# Main entry — top-level internal-error handler maps to exit code 3
# ---------------------------------------------------------------------------


def _usage_error(msg: str) -> None:
    print(f"USAGE ERROR: {msg}", file=sys.stderr)
    print("Run 'python scripts/verify.py help' for usage.", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Federation Verification Engine", add_help=False)
    parser.add_argument("command", nargs="?", default="help")
    parser.add_argument("--changed", action="store_true")
    parser.add_argument("--allowlist", default=None)
    parser.add_argument("--inventory", default=None)
    parser.add_argument("--ack", default=None,
                        help=f"acknowledgement flag for collect (must be {COLLECT_ACK_FLAG})")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--mode", choices=["strict", "discover"], default="strict")
    parser.add_argument("--paths", nargs="*")
    parser.add_argument("--repo-root", default=None,
                        help="explicit repository root (overrides script-location resolution)")
    args = parser.parse_args()

    # Re-resolve paths if --repo-root was provided
    global REPO_ROOT, GAME_ROOT, PROJECT_DIRS
    if args.repo_root:
        REPO_ROOT = Path(args.repo_root).resolve()
        GAME_ROOT = _resolve_game_root_for(REPO_ROOT)
        PROJECT_DIRS = {
            "backend": GAME_ROOT / "backend",
            "tests": GAME_ROOT / "tests",
            "npc_agent": GAME_ROOT / "npc-agent",
            "frontend": GAME_ROOT / "frontend",
            "routes": GAME_ROOT / "backend" / "routes",
        }

    valid_commands = {"syntax", "syntax-broad", "discover-static", "collect",
                      "tests-isolated", "frontend", "frontend-source", "all", "help"}
    if args.command not in valid_commands:
        _usage_error(f"unknown command: {args.command!r}")

    if args.command == "help":
        print(HELP_TEXT)
        sys.exit(0)

    try:
        v = Verifier(mode=args.mode, changed_only=args.changed)
        try:
            if args.command == "all":
                v.run_all()
            elif args.command == "syntax":
                v.run_syntax(paths=args.paths if args.paths else None)
            elif args.command == "syntax-broad":
                v.run_syntax_broad(paths=args.paths if args.paths else None)
            elif args.command == "discover-static":
                v.run_discover_static()
            elif args.command == "frontend":
                v.run_frontend()
            elif args.command == "frontend-source":
                v.run_frontend_source()
            elif args.command == "collect":
                v.run_collect(ack=args.ack, timeout=args.timeout)
            elif args.command == "tests-isolated":
                v.run_tests_isolated(allowlist_path=args.allowlist,
                                     inventory_path=args.inventory,
                                     timeout=args.timeout)
        finally:
            v._flush()
            dur = time.time() - v.t0
            code = v.exit_code()
            fails = sum(1 for r in v.results if r.state in ("FAIL", "UNAVAILABLE"))
            print(f"\nVerified {args.command} ({dur:.1f}s) [exit {code}]")
            print(f"   Artifacts: {v.artifact_dir}")
            if fails:
                print(f"   {fails} check(s) FAILED/UNAVAILABLE")
            sys.exit(code)
    except SystemExit:
        raise
    except Exception as e:
        print(f"INTERNAL ENGINE ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
