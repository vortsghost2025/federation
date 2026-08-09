#!/usr/bin/env python3
"""
Semantic Dedup + Outcome Feedback Monitor.

Runs on the VPS host (has docker access). Each cycle it:
  1. Scans the pair's recent artifacts for semantic near-duplicates (same
     content under different titles) that slipped past the live guard.
  2. Summarizes the outcome-feedback ledger so the operator/agent can see
     what produced what (which artifacts worked, which were dead ends).
  3. Writes a compact report to the dagu/dag state dir and Redis for the
     supervisor + Hermes digest to consume.

Exit codes (dagu convention):
  0 = healthy, nothing notable
  1 = WARNING (drift/noise worth a look)
  2 = CRITICAL (semantic bloat cluster detected)

Usage:
    python3 monitoring/semantic_dedup_monitor.py
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = "/docker/federation-game"
REDIS = ["docker", "exec", "federation-game-redis-1", "redis-cli"]
PAIR = "npc_pair:char_001__char_306"
SEM_DEDUP_SIM = float(os.environ.get("SEM_DEDUP_SIM", "0.72"))
SEM_DEDUP_WINDOW = int(os.environ.get("SEM_DEDUP_WINDOW", "12"))
OUTCOME_CAP = int(os.environ.get("OUTCOME_CAP", "12"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rd(*args):
    """Run a redis-cli command, returning stripped stdout."""
    try:
        out = subprocess.run(REDIS + list(args), capture_output=True, text=True, timeout=15)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _tokens(text):
    import re
    stop = {
        "the", "of", "and", "a", "an", "to", "in", "for", "on", "with",
        "from", "by", "at", "is", "it", "as", "be", "or", "that", "this",
        "its", "are", "was", "but", "not", "all", "being", "have", "has",
        "been", "will", "would", "could", "should", "analysis", "report",
        "overview", "summary", "data", "assessment", "recommendation",
        "strategy", "strategic", "response", "impact", "update", "review",
        "comprehensive", "final", "interim",
    }
    return {w for w in re.findall(r"[a-zA-Z]{3,}", (text or "").lower()) if w not in stop}


def _overlap(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _recent_artifacts(char_id, n=SEM_DEDUP_WINDOW):
    """Return the most recent artifact records for a char (oldest-first)."""
    raw = rd("LRANGE", f"npc_artifacts:{char_id}", f"{-n}", "-1")
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def scan_semantic_dups():
    """Return a list of near-duplicate pairs found within the window."""
    arts = {}
    for cid in ("char_001", "char_306"):
        arts[cid] = _recent_artifacts(cid)
    dups = []
    seen = set()
    for cid, items in arts.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                key = tuple(sorted([a.get("artifact_id", ""), b.get("artifact_id", "")]))
                if key in seen or not all(key):
                    continue
                seen.add(key)
                score = _overlap(
                    f"{a.get('title','')} {a.get('content','')}",
                    f"{b.get('title','')} {b.get('content','')}",
                )
                if score >= SEM_DEDUP_SIM:
                    dups.append({
                        "a": a.get("title", "?"),
                        "b": b.get("title", "?"),
                        "similarity": round(score, 2),
                        "char_id": cid,
                    })
    return dups


def summarize_outcomes():
    """Return a compact summary of the shared outcome-feedback ledger."""
    raw = rd("LRANGE", f"{PAIR}:outcomes", "0", str(OUTCOME_CAP - 1))
    entries = []
    for line in raw.splitlines():
        try:
            e = json.loads(line)
            entries.append(f"  • {e.get('artifact_title','?')} → {e.get('outcome','')}")
        except Exception:
            continue
    return entries


def main():
    dups = scan_semantic_dups()
    outcomes = summarize_outcomes()

    report = {
        "ts": now_iso(),
        "semantic_duplicate_clusters": len(dups),
        "semantic_duplicates": dups[:5],
        "recent_outcomes": outcomes[:OUTCOME_CAP],
    }
    print(json.dumps(report, indent=2))

    # Write to a host state dir for the supervisor/Hermes digest.
    try:
        os.makedirs(f"{BASE}/monitoring/supervisor_state", exist_ok=True)
        with open(f"{BASE}/monitoring/supervisor_state/semantic_report.json", "w") as fh:
            json.dump(report, fh, indent=2)
    except Exception as e:
        print(f"WARN: could not write state file: {e}")

    # Publish to Redis for the supervisor + digest.
    try:
        rd("SET", "fed:semantic:report", json.dumps(report), "EX", "3600")
    except Exception:
        pass

    if dups:
        print(f"CRITICAL: {len(dups)} semantic duplicate cluster(s) detected")
        return 2
    if not outcomes:
        print("INFO: no outcome-feedback records yet (benign)")
        return 0
    print("OK: no semantic duplicates; outcome ledger present")
    return 0


if __name__ == "__main__":
    sys.exit(main())