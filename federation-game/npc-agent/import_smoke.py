"""Clean-process import smoke test for the modular NPC-agent package.

Run as a subprocess with no live Redis or network access. Each module is
imported and its absolute __file__ is printed and validated to prove it
resolves from THIS worktree, not another checkout or site-packages.

Usage:
    python import_smoke.py
"""

import importlib
import os
import sys

# Force resolution from this worktree only.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

EXPECTED_DIR = os.path.normcase(HERE)

MODULES = [
    "npc_loop_control",
    "npc_decisions",
    "npc_actions",
    "npc_agent",
]


def main():
    failures = []
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{mod_name}: IMPORT FAILED: {type(exc).__name__}: {exc}")
            continue
        fpath = getattr(mod, "__file__", None)
        if not fpath:
            failures.append(f"{mod_name}: no __file__")
            continue
        norm = os.path.normcase(os.path.abspath(fpath))
        ok = norm.startswith(EXPECTED_DIR)
        status = "OK" if ok else "WRONG-ORIGIN"
        print(f"{status} {mod_name} -> {norm}")
        if not ok:
            failures.append(f"{mod_name}: resolved outside worktree ({norm})")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("\nALL IMPORTS RESOLVED FROM WORKTREE")


if __name__ == "__main__":
    main()
