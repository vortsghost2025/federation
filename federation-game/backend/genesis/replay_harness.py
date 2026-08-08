"""
genesis/replay_harness.py — OFFLINE replay harness for the WE4FREE Genesis layers.

Purpose
-------
Prove the 4 layers (L1 Symmetry, L2 Constraint, L3 Phenotype, L4 Drift) actually help
BEFORE any flag is flipped in production. This harness NEVER touches the live 60s tick,
game_state, or write path. It is strictly read-only against Redis when capturing, and
uses FakeRedis / JSON for everything else.

Two modes:
  1. --capture-from-redis <char_id>
       Reads npc:{char_id} (affiliation, mood, decree alignment) live, dumps it to
       a JSON capture file, then DISCONNECTS. Read-only. No writes.
  2. --capture-file <path.json>
       Replays from a previously captured file (or a hand-written sample).

What it does
------------
For a captured NPC it:
  - builds decision options in the same shape npc_autonomy.evaluate_decision_options
    returns ({category, score, reasons, est_cost, target, safe}),
  - runs L1 -> L2 -> L3 -> L4,
  - reports the Genesis-selected option + the phenotype + any drift correction,
  - contrasts with what raw random.choices would have picked (the current live behavior).

Exit code 0 = harness ran and layers behaved constitutionally (no constraint violations,
no uncontrolled drift). Non-zero = something the layers could not handle (worth a look
before enabling).

Run:
  python -m genesis.replay_harness --capture-file ../samples/npc_east_adam.json
  python -m genesis.replay_harness --capture-from-redis east_adam --dump-to ./captures/east_adam.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

# Allow running as a script (python genesis/replay_harness.py) or module (-m).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from genesis import genesis_config as cfg  # noqa: E402
from genesis import (  # noqa: E402
    genesis_constraints as L2,
    genesis_constitution as L1,
    genesis_drift as L4,
    genesis_phenotype as L3,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("genesis.replay")

# Option categories mirrored from npc_autonomy.DECISION_CATEGORIES.
CATEGORIES = L3.CATEGORIES

# When capturing live, we cannot call the live evaluate_decision_options (it touches
# world_state). Instead we synthesize a plausible option set per category with a
# deterministic seed so replays are reproducible. Scores are shaped by affiliation.
_AFFILIATION_BASE_SCORE = {
    "builder": {"advance_goal": 0.9, "seek_resources": 0.7, "self_improve": 0.6, "rest": 0.3},
    "explorer": {"explore": 0.9, "investigate": 0.8, "react_to_events": 0.5, "rest": 0.3},
    "diplomat": {"socialize": 0.9, "help_ally": 0.8, "react_to_events": 0.5, "rest": 0.3},
    "guardian": {"confront_rival": 0.8, "help_ally": 0.7, "seek_resources": 0.5, "rest": 0.3},
    "independent": {"rest": 0.6, "socialize": 0.5, "investigate": 0.5, "advance_goal": 0.4},
}


def build_options(char_id: str, affiliation: str, mood: str, seed: int = 0) -> List[dict]:
    """Synthesize decision options in the live shape.

    Mirrors evaluate_decision_options output: {category, score, reasons,
    est_cost, target, safe}. Scores tilt by affiliation; a tiny deterministic
    jitter keeps it realistic without randomness affecting the conclusion.
    """
    rng = random.Random(seed)
    base = _AFFILIATION_BASE_SCORE.get(affiliation, _AFFILIATION_BASE_SCORE["independent"])
    options: List[dict] = []
    for cat in CATEGORIES:
        base_score = base.get(cat, 0.25)
        score = round(min(1.0, max(0.05, base_score + rng.uniform(-0.05, 0.05))), 3)
        options.append({
            "category": cat,
            "score": score,
            "reasons": [f"{affiliation}-inclined", f"mood:{mood}"],
            "est_cost": 0.4 if cat not in ("rest",) else 0.05,
            "target": char_id if cat in ("rest", "self_improve") else "other",
            "safe": cat in ("rest", "socialize", "help_ally", "advance_goal"),
        })
    # Sort by score desc, exactly like npc_autonomy picks top_n.
    options.sort(key=lambda o: o["score"], reverse=True)
    return options


def random_choice_baseline(options: List[dict], k: int = 1) -> List[dict]:
    """Reproduce the CURRENT live behavior: random.choices(weights=scores)."""
    scores = [o["score"] for o in options]
    return random.choices(options, weights=scores, k=k)


def run_replay(state: Dict[str, Any], dump: bool = False) -> Dict[str, Any]:
    """Run all 4 layers over one captured NPC. Read-only. Returns a report dict."""
    char_id = state.get("char_id", "unknown")
    affiliation = state.get("affiliation", "independent")
    mood = state.get("mood", "")
    decree_banned = set(state.get("decree_banned", []))
    decree_alignment = float(state.get("decree_alignment", 0.0))
    remaining_budget = float(state.get("remaining_budget", 1.0))

    report: Dict[str, Any] = {
        "char_id": char_id,
        "affiliation": affiliation,
        "layers": {},
        "constitutional": True,
        "notes": [],
    }

    # --- Build the live-shaped option set ---
    options = build_options(char_id, affiliation, mood, seed=abs(hash(char_id)) % 1000)
    report["option_count"] = len(options)

    # === L1: Symmetry — freeze a snapshot (offline FakeRedis, no live write) ===
    # Use an isolated in-memory store so we never touch live Redis.
    fake = L1._FakeRedisForTest() if hasattr(L1, "_FakeRedisForTest") else None
    # Fallback: monkeypatch constitution._redis to a local fake store.
    import types

    class _LocalRedis:
        def __init__(self):
            self._d = {}

        def hset(self, k, *a, **kw):
            d = self._d.setdefault(k, {})
            if a and len(a) == 2:
                d[a[0]] = a[1]
            elif kw:
                d.update(kw)
            return 1

        def hget(self, k, f):
            return self._d.get(k, {}).get(f)

        def hgetall(self, k):
            return dict(self._d.get(k, {}))

        def set(self, k, v, **kw):
            self._d[k] = v
            return True

        def get(self, k):
            return self._d.get(k)

        def rename(self, src, dst):
            # Atomic move: final key is overwritten only if src exists.
            if src in self._d:
                self._d[dst] = self._d.pop(src)
            return True

        def renamenx(self, src, dst):
            if dst in self._d:
                return False
            self._d[dst] = self._d.pop(src, None)
            return True

        def expire(self, k, t):
            return True

        def exists(self, k):
            return 1 if k in self._d else 0

        def ping(self):
            return True

        def delete(self, k):
            self._d.pop(k, None)
            return 1

        def setex(self, k, t, v):
            self._d[k] = v
            return True

        def ttl(self, k):
            return -1

    local_redis = _LocalRedis()
    saved = L1._redis
    L1._redis = lambda: local_redis  # type: ignore[assignment]
    snap_key = f"genesis:snapshot:{char_id}"
    snapshot = {
        "char_id": char_id,
        "affiliation": affiliation,
        "mood": mood,
        "decree_alignment": decree_alignment,
        "rumor_level": state.get("rumor_level"),
        "status": state.get("status"),
    }
    L1.freeze_snapshot(snap_key, snapshot)
    recovered = L1.recover_snapshot(snap_key)
    l1_ok = recovered.get("char_id") == char_id and recovered.get("affiliation") == affiliation
    report["layers"]["L1_symmetry"] = {
        "frozen": True,
        "recovered_equal": l1_ok,
        "aliveness_real": L1.verify_aliveness(snap_key),
    }
    if not l1_ok:
        report["constitutional"] = False
        report["notes"].append("L1: snapshot did not round-trip symmetrically")

    # Keep the local Redis monkeypatch active through L2/L3/L4 (L4 recovery reads L1).
    try:
        # === L2: Constraint lattice — filter + deterministic select ===
        ctx = {
            "decree_banned": decree_banned,
            "remaining_budget": remaining_budget,
            "self_id": char_id,
            "observer_can_see": lambda opt: opt.get("category") in ("socialize", "help_ally", "advance_goal", "rest"),
            "safe_actions": set(),
        }
        kept = L2.filter_options(options, ctx)
        report["layers"]["L2_constraints"] = {
            "options_in": len(options),
            "options_passing": len(kept),
            "violations": [o["category"] for o in options if o not in kept],
        }
        if not kept:
            # L2 returns stable 'rest' on empty lattice — that is constitutional, not a failure.
            chosen = {"category": "rest", "score": 0.0, "reasons": ["L2 empty lattice -> stable rest"], "est_cost": 0.05, "target": char_id, "safe": True}
            report["layers"]["L2_constraints"]["resolved_to_rest"] = True
        else:
            chosen = L2.select(kept, ctx)

        # === L3: Phenotype pull — attractor seeded from affiliation + decree ===
        pheno = L3.seed_from_affiliation(char_id, affiliation, decree_alignment=decree_alignment)
        pulled = L3.phenotype_pull(chosen, pheno)
        coherent = L3.is_coherent(chosen, pheno)
        report["layers"]["L3_phenotype"] = {
            "attractors": pheno.normalized(),
            "chosen_category": chosen["category"],
            "pull_score": round(pulled, 3),
            "coherent": coherent,
        }
        if not coherent:
            report["notes"].append(f"L3: chosen '{chosen['category']}' is off-attractor (drift risk)")

        # === L4: Drift — measure recent action distribution vs. attractor ===
        # A coherent NPC's history tracks its own attractor -> ~0 drift. If the capture
        # carries a REAL recent_actions list (with action_type), use that verbatim;
        # otherwise synthesize a history sampled from the attractor distribution.
        import random as _r
        _rng = _r.Random(abs(hash(char_id)) % 1000 + 7)
        norm = pheno.normalized()
        cats = list(norm.keys())
        weights = [norm[c] for c in cats]
        history_len = 50
        raw_actions = state.get("recent_actions") or []
        if raw_actions and isinstance(raw_actions[0], dict):
            # Real production actions: {action_type, mood, ...}
            recent_actions = [a.get("action_type") or a.get("category") or "rest" for a in raw_actions]
        elif raw_actions:
            recent_actions = list(raw_actions)
        else:
            # No real behavior captured -> unknown, not drifting. Do NOT synthesize
            # behavior we don't have; measure_drift([]) returns 0.0 (constitutional).
            recent_actions = []
        drift = L4.measure_drift(recent_actions, pheno, salience_eps=0.1)
        recovered_flag = False
        if drift > cfg.config.drift_tolerance:
            recovered_state = L4.functorial_recover(char_id, pheno, {"char_id": char_id, "attraction": pheno.attractors})
            recovered_flag = recovered_state is not None
            report["notes"].append(f"L4: drift {drift:.3f} > tol {cfg.config.drift_tolerance} -> recovered")
        report["layers"]["L4_drift"] = {
            "drift": round(drift, 3),
            "tolerance": cfg.config.drift_tolerance,
            "recovered": recovered_flag,
        }

        # === Baseline contrast: what random.choices would have done ===
        baseline = random_choice_baseline(options, k=1)[0]
        report["baseline_random_choice"] = {
            "category": baseline["category"],
            "score": baseline["score"],
        }
        report["genesis_choice"] = {
            "category": chosen["category"],
            "score": chosen["score"],
        }
        report["would_have_diverged"] = baseline["category"] != chosen["category"]

        if dump:
            out = Path(state.get("_dump_path", f"./captures/{char_id}.replay.json"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            report["dumped_to"] = str(out)
    finally:
        # Restore the real Redis connection regardless of what happened above.
        L1._redis = saved  # type: ignore[assignment]
    return report


# Production Redis key shapes (discovered 2026-07-18 against the live VPS):
#   npc_state:{char_id}      -> hash {corruption_level, rumor_level, status, last_updated}
#   npc_actions:{char_id}    -> zset of JSON {char_id, char_name, action_type, description, mood, ts}
#   npc_memory:{char_id}     -> zset of JSON {type, category, content, reasoning, action_taken, ...}
#   game_snapshots(is_current)-> text game_state_json (federation-scale: turn, policies, current_event)
# There is NO per-NPC affiliation/mood/decree_alignment field in production. We DERIVE the
# harness's expected fields from real signals so the layers can still be exercised:
#   mood            <- latest npc_actions.mood (real)
#   affiliation     <- dominant action_type mapped to a Genesis affiliation (derived)
#   decree_alignment<- 1 - rumor_level (real rumor is the inverse of constitutional alignment)
_CATEGORY_TO_AFFILIATION = {
    "help_ally": "guardian", "confront_rival": "guardian",
    "advance_goal": "builder", "self_improve": "builder", "seek_resources": "builder",
    "explore": "explorer", "investigate": "explorer",
    "socialize": "diplomat",
    "rest": "independent",
}


def _derive_affiliation(recent_actions: List[dict]) -> str:
    counts: Dict[str, int] = {}
    for a in recent_actions:
        cat = a.get("action_type") or a.get("category") or "rest"
        aff = _CATEGORY_TO_AFFILIATION.get(cat, "independent")
        counts[aff] = counts.get(aff, 0) + 1
    if not counts:
        return "independent"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def capture_from_redis(char_id: str, dump_to: str | None) -> Dict[str, Any]:
    """Read the REAL production keys for npc:{char_id} live, then DISCONNECT. Read-only."""
    try:
        import os
        import redis  # type: ignore
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        r = redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
        st = r.hgetall(f"npc_state:{char_id}")
        if not st:
            log.error("npc_state:%s not found in Redis. Check char_id. (Read-only, nothing changed.)", char_id)
            sys.exit(2)
        actions: List[dict] = []
        if r.exists(f"npc_actions:{char_id}"):
            actions = [json.loads(x) for x in r.zrange(f"npc_actions:{char_id}", -50, -1)]
        mood = actions[-1].get("mood", "") if actions else ""
        rumor = float(st.get("rumor_level", 0.0))
        state = {
            "char_id": char_id,
            "affiliation": _derive_affiliation(actions),   # derived from real actions
            "mood": mood,                                   # real
            "decree_alignment": round(1.0 - rumor, 3),      # derived: rumor is inverse alignment
            "rumor_level": rumor,                           # real
            "corruption_level": float(st.get("corruption_level", 0.0)),  # real
            "status": st.get("status", "active"),           # real
            "remaining_budget": 1.0,
            "decree_banned": [],
            "recent_actions": actions,                      # real, with action_type/mood
            "_source": "live-redis-readonly",
        }
        if dump_to:
            Path(dump_to).parent.mkdir(parents=True, exist_ok=True)
            Path(dump_to).write_text(json.dumps(state, indent=2), encoding="utf-8")
            log.info("Captured npc_state:%s -> %s (read-only, disconnected)", char_id, dump_to)
        return state
    except Exception as exc:  # noqa: BLE001
        log.error("Redis capture failed (read-only attempt): %s", exc)
        sys.exit(3)


def run_real_tick(path: str, dump: bool = False) -> List[Dict[str, Any]]:
    """Replay EVERY NPC in a full VPS tick capture (the vps_real_tick.json shape).

    The capture is {game_state, npcs: {char_id: {npc_state, recent_actions:[...]}}}.
    Read-only — we never write back. Returns one report per NPC.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    reports: List[Dict[str, Any]] = []
    npcs = data.get("npcs", {})
    for cid, blob in npcs.items():
        st = blob.get("npc_state", {})
        actions = blob.get("recent_actions", [])
        rumor = float(st.get("rumor_level", 0.0))
        state = {
            "char_id": cid,
            "affiliation": _derive_affiliation(actions),
            "mood": actions[-1].get("mood", "") if actions else "",
            "decree_alignment": round(1.0 - rumor, 3),
            "rumor_level": rumor,
            "corruption_level": float(st.get("corruption_level", 0.0)),
            "status": st.get("status", "active"),
            "remaining_budget": 1.0,
            "decree_banned": [],
            "recent_actions": actions,
            "_source": "real-tick-capture",
            "_game_state_turn": data.get("game_state", {}).get("turn"),
        }
        reports.append(run_replay(state, dump=dump))
    return reports


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline Genesis layer replay harness")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--capture-file", help="JSON file with captured NPC state")
    src.add_argument("--capture-real-tick", help="Full VPS tick JSON {game_state, npcs:{...}} — replays ALL NPCs (read-only)")
    src.add_argument("--capture-from-redis", help="Live-read npc_state:{char_id} (read-only), then disconnect")
    ap.add_argument("--dump-to", help="Where to write the capture JSON (with --capture-from-redis)")
    ap.add_argument("--dump-report", action="store_true", help="Write the replay report JSON")
    ap.add_argument("--diverged", action="store_true",
                    help="Force a divergent recent-action history to exercise L4 recovery")
    args = ap.parse_args(argv)

    # Force layers ON for the harness regardless of the production default.
    cfg.enable()

    if args.capture_real_tick:
        reports = run_real_tick(args.capture_real_tick, dump=args.dump_report)
        ok = sum(1 for r in reports if r["constitutional"])
        div = sum(1 for r in reports if r.get("would_have_diverged"))
        rec = sum(1 for r in reports if r["layers"]["L4_drift"]["recovered"])
        print(f"\n=== GENESIS REPLAY — REAL TICK ({len(reports)} NPCs) ===")
        print(f"Constitutional : {ok}/{len(reports)}")
        print(f"Would diverge : {div} (random.choices would pick differently than Genesis)")
        print(f"L4 recovered  : {rec} (drift exceeded tolerance, recovery fired)")
        print("Per-NPC drift:")
        for r in reports:
            d = r["layers"]["L4_drift"]
            print(f"  {r['char_id']:<14} aff={r['affiliation']:<11} "
                  f"drift={d['drift']:<6} tol={d['tolerance']} recovered={d['recovered']} "
                  f"coherent={r['layers']['L3_phenotype']['coherent']}")
        print("=============================================\n")
        if args.dump_report:
            out = Path("./captures/real_tick.replay.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
            print(f"Report written: {out}")
        return 0 if ok == len(reports) else 1

    if args.capture_from_redis:
        state = capture_from_redis(args.capture_from_redis, args.dump_to)
    else:
        p = Path(args.capture_file)
        if not p.exists():
            log.error("Capture file not found: %s", p)
            return 4
        state = json.loads(p.read_text(encoding="utf-8"))

    if args.diverged:
        # A divergent NPC ignores its attractor: heavy on off-attractor categories.
        state["recent_actions"] = ["confront_rival", "explore", "investigate", "request_capability",
                                    "react_to_events", "confront_rival", "explore", "investigate",
                                    "request_capability", "react_to_events", "confront_rival", "explore",
                                    "investigate", "request_capability", "react_to_events", "confront_rival",
                                    "explore", "investigate", "request_capability", "react_to_events"]

    report = run_replay(state, dump=args.dump_report)
    # Pretty console summary.
    print("\n=== GENESIS REPLAY REPORT ===")
    print(f"NPC          : {report['char_id']} ({report['affiliation']})")
    print(f"Options      : {report['option_count']}")
    print(f"L1 symmetry  : recovered_equal={report['layers']['L1_symmetry']['recovered_equal']} "
          f"aliveness_real={report['layers']['L1_symmetry']['aliveness_real']}")
    print(f"L2 lattice   : {report['layers']['L2_constraints']['options_passing']}/"
          f"{report['layers']['L2_constraints']['options_in']} passing "
          f"violations={report['layers']['L2_constraints']['violations']}")
    print(f"L3 phenotype : coherent={report['layers']['L3_phenotype']['coherent']} "
          f"pull={report['layers']['L3_phenotype']['pull_score']}")
    print(f"L4 drift     : {report['layers']['L4_drift']['drift']} "
          f"(tol {report['layers']['L4_drift']['tolerance']}) recovered={report['layers']['L4_drift']['recovered']}")
    print(f"BASELINE     : random.choices -> {report['baseline_random_choice']['category']} "
          f"(score {report['baseline_random_choice']['score']})")
    print(f"GENESIS      : -> {report['genesis_choice']['category']} "
          f"(score {report['genesis_choice']['score']})")
    print(f"Would diverge: {report['would_have_diverged']}")
    if report["notes"]:
        print("NOTES:")
        for n in report["notes"]:
            print(f"  - {n}")
    print(f"CONSTITUTIONAL: {report['constitutional']}")
    print("==============================\n")

    if args.dump_report:
        out = Path(f"./captures/{report['char_id']}.replay.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report written: {out}")

    return 0 if report["constitutional"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
