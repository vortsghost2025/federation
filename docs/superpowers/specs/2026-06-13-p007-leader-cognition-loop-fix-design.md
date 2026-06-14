# P007 — Leader Cognition Retry Loop Fix

**Date:** 2026-06-13
**Status:** Approved
**Author:** opencode (with user)
**Scope:** Two-file surgical repair. No abstractions, no new dependencies.

---

## Problem

The `/npc-turns/analyze` endpoint surfaces five anomaly codes for every leader-tier NPC (`char_101` through `char_108`):

| Anomaly code          | Affects       | Failure type in data      |
|-----------------------|---------------|---------------------------|
| `latency_spike`       | 8 / 8 leaders | max_latency 50–95s        |
| `provider_drift`      | 7 / 8 leaders | llama-70b <-> nemotron-49b |
| `provider_fallbacks`  | 7 / 8 leaders | 30–48% fallback rate      |
| `unparseable_output`  | 5 / 8 leaders | `parse_unparseable`       |
| `repeated_loop`       | 8 / 8 leaders | 2+ turns with same output |

All eight NPCs share `task_class=leader`. No specialist, worker, or other tier appears in the anomaly set.

## Root cause (two defects)

### Defect A — Tight timeout on a slow primary model

`federation-game/backend/llm_router.py:497–520`:

```python
"leader": {
    "primary": {
        "provider": "nim",
        "model": "meta/llama-3.3-70b-instruct",
        "max_tokens": 300,
        "timeout": 8,            # real-world p50 is 10s, max 95s
    },
    ...
```

Measured latency on production (8 leaders ~ 60 turns sampled via `/npc-turns/analyze?limit=500`):

| NPC          | avg_latency_ms | max_latency_ms |
|--------------|----------------|-----------------|
| char_101     | (not measured, but flagged) | — |
| char_104     | 11,576         | 95,444          |
| char_108     | 10,111         | 50,477          |
| other leaders | ~9,000–11,000 | 50,477+         |

8 seconds is shorter than the **average** observed call. The majority of leader cognition calls exceed the timeout, fall back to `nvidia/llama-3.3-nemotron-super-49b-v1.5`, and frequently that fallback also times out (10s is also short). Result: >30% `fallback_rate` and per-call latency averaging 10–12s as measured by `route_call`.

`specialist` (lines 521–542) uses the same primary model with timeout=6, same defect class, just less visible because specialists only cognize when triggered (rate-limited by `npc_list` triggers, not by ambient 15%).

`worker` (lines 544–566) uses `meta/llama-3.1-8b-instruct`, a genuinely faster model, so the 12s timeout holds.

### Defect B — No cooldown on failure

`federation-game/backend/npc_cognition.py:887–960` (leader branch) and `:995–1062` (specialist branch):

```python
if llm_result["success"]:
    decision = _parse_llm_response(...)
    if decision:
        ...                                        # success path
        _set_cooldown(cid)                         # line 932 — only here
        log_npc_activity(cid, "cognition", {...})
    else:
        turn_error_code = "parse_unparseable"      # line 941 — FAILURE: no cooldown
        ...
else:
    turn_error_code = "llm_failed"                 # line 945 — FAILURE: no cooldown
    ...
```

`_set_cooldown` is only called on the **success-and-parsed** path. When the LLM times out (Defect A) or returns unparseable output, no cooldown is set. The next tick (60 seconds later) hits `_is_on_cooldown` -> `False` -> re-runs the same leader with the same prompt -> same outcome -> linear buildup at one attempt per tick (60s) until world state changes. After 24 hours: ~1,440 identical broken turns per affected leader.

The analyzer in `federation-game/backend/routes/npc_logs.py:36–37` then flags `repeated_loop` because it counts distinct leading 80-char previews of `output_text`:

```python
output_previews = Counter(
    (r.get("output_text") or "")[:80] for r in rows if r.get("output_text")
)
repeated_outputs = [text for text, count in output_previews.items() if text and count >= 2]
```

Defect B guarantees the same leading 80 chars appear 50+ times in the log.

### Why B looks like an NPC-behavior problem

The chain `A -> [timeouts, fallback, parse-fail] -> B -> [unbounded retries] -> repeated identical log entries` is misread from the dashboard as "NPCs are thinking the same thing" or "the cache is broken". Neither is true. The cause is structural: failures do not back off.

---

## Fix

Two edits. No abstractions. YAGNI.

### Edit 1 — `federation-game/backend/llm_router.py`

Bump timeouts on `leader` and `specialist` task classes. `worker` stays as-is.

**`leader` block (lines ~497–520):**
- `primary.timeout`: 8 -> **30**
- `primary.max_tokens`: 300 -> **400** (longer reasoning sometimes truncates at 300)
- `fallback_nim.timeout`: 10 -> **30**
- `fallback_openrouter.timeout`: 12 -> **30**

**`specialist` block (lines ~521–542):**
- `primary.timeout`: 6 -> **30**
- `fallback_nim.timeout`: 8 -> **30**
- `fallback_openrouter.timeout`: 10 -> **30**

**Worker (lines ~544–566):** no change.

30 seconds is ~3x the measured p50 and 1/3 of observed max, with headroom for transient NIM slowdowns. Anything tighter risks re-introducing Defect A under load.

### Edit 2 — `federation-game/backend/npc_cognition.py`

Add cooldown on the failure paths. Failure cooldown is **longer** than success cooldown to give a broken path real back-off.

**At line ~104, alongside `LEADER_COOLDOWN = 180`:**

```python
LEADER_COOLDOWN_FAILURE = 600        # 10 min — back off a broken path
SPECIALIST_COOLDOWN_FAILURE = 300    #  5 min
```

**Leader branch — track whether cooldown was set; set on failure if not. Around lines 899–949:**

Currently:
```python
if llm_result["success"]:
    decision = _parse_llm_response(...)
    if decision:
        ...
        _set_cooldown(cid)
        log_npc_activity(...)
    else:
        turn_error_code = "parse_unparseable"
        result["stats"]["calls_failed"] += 1
        result["errors"].append(...)
else:
    turn_error_code = "llm_failed"
    result["stats"]["calls_failed"] += 1
    result["errors"].append(...)

_log_cognition_turn(cid, "leader", ...)
```

After:
```python
cooldown_set = False
if llm_result["success"]:
    decision = _parse_llm_response(...)
    if decision:
        ...
        _set_cooldown(cid, LEADER_COOLDOWN)
        log_npc_activity(...)
        cooldown_set = True
    else:
        turn_error_code = "parse_unparseable"
        result["stats"]["calls_failed"] += 1
        result["errors"].append(...)
else:
    turn_error_code = "llm_failed"
    result["stats"]["calls_failed"] += 1
    result["errors"].append(...)

if not cooldown_set:
    _set_cooldown(cid, LEADER_COOLDOWN_FAILURE)

_log_cognition_turn(cid, "leader", ...)
```

**Specialist branch — same pattern, around lines 1006–1062.**

**`_set_cooldown` signature change (line ~379):**

```python
def _set_cooldown(char_id: str, duration: int) -> None:
    """Set NPC cooldown for `duration` seconds. Caller passes the right value:

    LEADER_COOLDOWN              (180s) - normal leader gap
    LEADER_COOLDOWN_FAILURE      (600s) - back off a broken leader path
    SPECIALIST_COOLDON_FAILURE   (300s) - back off a broken specialist path
    """
    ...
```

Caller selects duration explicitly (no embedded default). The old logic on line ~367 inferred duration from a tier string; removing it makes the call sites self-documenting.

`SPECIALIST_COOLDON` already exists at line ~102 - keep its current value; this edit does not change it.

All callers (5 in `npc_cognition.py`, 1 in `routes/pcs.py`) must pass a duration.

After Edit 2, `routes/pcs.py:130–136` reads:

```python
duration = LEADER_COOLDOWN if tier == "leader" else SPECIALIST_COOLDON
_set_cooldown(char_id, duration)
```

Pure refactor at that callsite; behavior preserved.

---

## Verification

**New file: `S:/federation/scripts/p007-deploy-check.sh`**

```bash
#!/usr/bin/env bash
# P007 deploy verification - leader cognition loop fix
set -euo pipefail

SSH_HOST="root@187.77.3.56"
SSH_KEY="${HOME}/.ssh/id_ed25519"
PRIMARY="federation-game-backend-1"

ssh_run() {
  ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_HOST" "$1"
}

# Step 1: Confirm new code is live (LEADER_COOLDOWN_FAILURE present)
count=$(ssh_run "docker exec $PRIMARY grep -c LEADER_COOLDOWN_FAILURE /app/npc_cognition.py")
if [ "$count" -eq 0 ]; then
  echo "FAIL: LEADER_COOLDOWN_FAILURE missing from deployed npc_cognition.py"
  exit 1
fi
echo "OK: deploy contains failure-cooldown constant"

# Step 2: Confirm TIMEOUT 30 bumped in TASK_MODELS
count=$(ssh_run "docker exec $PRIMARY grep -cE '\"timeout\": 30' /app/llm_router.py")
if [ "$count" -lt 1 ]; then
  echo "FAIL: TASK_MODELS timeout 30 not found in deployed llm_router.py"
  exit 1
fi
echo "OK: deploy contains 30s primary timeouts"

# Step 3: Wait 5 minutes for fresh leader cognition turns, then check the analyzer
echo "Waiting 5 minutes for 3+ fresh leader cognition turns to accumulate..."
sleep 300

analyze_cmd='python3 -c "import urllib.request as u, json, sys; d=json.loads(u.urlopen(chr(0x68)+chr(0x74)+chr(0x74)+chr(0x70)+chr(0x3a)+chr(0x2f)+chr(0x2f)+chr(0x31)+chr(0x32)+chr(0x37)+chr(0x2e)+chr(0x30)+chr(0x2e)+chr(0x30)+chr(0x2e)+chr(0x31)+chr(0x3a)+chr(0x38)+chr(0x30)+chr(0x30)+chr(0x30)+chr(0x2f)+chr(0x6e)+chr(0x70)+chr(0x63)+chr(0x2d)+chr(0x74)+chr(0x75)+chr(0x72)+chr(0x6e)+chr(0x73)+chr(0x2f)+chr(0x61)+chr(0x6e)+chr(0x61)+chr(0x6c)+chr(0x79)+chr(0x7a)+chr(0x65)+chr(0x3f)+chr(0x6c)+chr(0x69)+chr(0x6d)+chr(0x69)+chr(0x74)+chr(0x3d)+chr(0x35)+chr(0x30)+chr(0x30), timeout=20).read().decode()); flagged=[r for r in d.get(\"fleet\", []) if r.get(\"online\") and r.get(\"anomalies\")]; print(len(flagged))"'

hits=$(ssh_run "docker exec $PRIMARY $analyze_cmd")

if [ "$hits" -gt 0 ]; then
  echo "FAIL: $hits leaders still flagged online after fix"
  exit 1
fi

echo "OK: 0 leaders flagged online in 600s window - loop fixed"
```

Operator runs this after the deploy. 5-minute wait gives the worker room to log enough turns that the analyzer's online-flag (`now - latest_turn < 600s`) is still meaningful.

The inline `chr()` encoding in step 3 sidesteps shell-escape pitfalls around the URL — same technique I used to fetch the live data during the investigation.

**Manual follow-up (after 1 hour):**

```bash
ssh root@187.77.3.56 "curl -s 'http://localhost:8000/npc-turns/analyze?limit=2000'" \
  | python -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for a in d['alerts'] if a['type']=='repeated_loop'))"
```

Pre-fix baseline: 35 alerts across the 2000-turn window, of which 8 are from leaders (1 per leader) for the `online` (`now - latest_turn < 600s`) subset. After fix, expect the alert count to drop to 0 within ~10 minutes (one failure cooldown cycle) and stay at 0 as fresh broken turns stop accumulating.

---

## What this does NOT touch

YAGNI list. Reject any plan-phase additions in these areas without explicit user approval.

- No abstraction for failure-aware timeout policy; direct numeric edits only
- No new Redis keys, no schema migrations, no new anomaly codes
- No frontend changes (`npc-logs.html` and `spectator.js` already render whatever `/npc-turns/analyze` returns; the user reports are dashboard cards, not behavior concerns)
- No changes to `npc_logs.py` analyzer logic (its flags are correct given the data)
- No regression work on NPCs `char_201`–`205`, `comp_002`–`010` etc; they don't appear in the npc-turns anomaly surface
- No telemetry-schema additions; existing `turn_error_code` field suffices
- The `_set_cooldown` signature change is local (5 callers in `npc_cognition.py` and 1 in `routes/pcs.py`); does not warrant strategy/protocol patterns

---

## Files changed

| File | Change |
|------|--------|
| `federation-game/backend/llm_router.py` | TASK_MODELS timeout/max_tokens bumps in `leader` and `specialist` blocks |
| `federation-game/backend/npc_cognition.py` | `LEADER_COOLDOWN_FAILURE` / `SPECIALIST_COOLDOWN_FAILURE` constants; `_set_cooldown` accepts explicit duration; cooldown set on failure paths |
| `scripts/p007-deploy-check.sh` | New file: verification |

## Deploy

Standard VPS pipe-over-SSH sequence (per `FEDERATION_INDEX.md`):

1. Locally edit the two backend files.
2. Verify formatting / lint: `ruff check federation-game/backend/llm_router.py federation-game/backend/npc_cognition.py`.
3. SCP files to VPS `/tmp/`.
4. SSH: `cp /tmp/FILE.py /docker/federation-game/backend/ && docker exec federation-game-backend-1 find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; docker restart federation-game-backend-1`.
5. Restart worker: `docker restart federation-game-worker-1` (so the new constants take effect on every tick).
6. Run `scripts/p007-deploy-check.sh` from local machine.
7. Commit. Update `.horizon/HORIZIZON_STATUS.md` to completed.
