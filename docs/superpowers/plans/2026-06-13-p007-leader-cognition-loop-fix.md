# P007 — Leader Cognition Retry Loop Fix — Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Drop this in a fresh subagent (recommended) or execute inline.

**Goal:** Stop the unbounded retry of broken leader cognition calls by fixing two structural defects (timeout and cooldown-on-failure), verifiable by `/npc-turns/analyze` returning 0 online-flagged leaders within 5 minutes of deploy.

**Architecture:** Two numeric timeouts bump in `TASK_MODELS` for `leader` and `specialist` blocks. New `LEADER_COOLDOWN_FAILURE` and `SPECIALIST_COOLDOWN_FAILURE` constants. `_set_cooldown` gains an explicit `duration` parameter; leader and specialist branches in `run_cognition` set cooldown on every code path. New `scripts/p007-deploy-check.sh` verifier runs against the production deploy.

**Tech Stack:** Python 3 (Flask backend), Redis (cooldown keys), Docker (deploy), bash (verification).

---

## File Structure

| File | Change | Lines touched |
|------|--------|---------------|
| `federation-game/backend/llm_router.py` | TASK_MODELS leader + specialist numeric bumps | ~497–542 |
| `federation-game/backend/npc_cognition.py` | Cooldown constants, function signature, two call sites | ~104, ~379, ~932, ~1034 |
| `scripts/p007-deploy-check.sh` | New file | full |

No new dependencies. No migrations. No frontend changes.

---

## Task 1 — Bump TASK_MODELS timeouts (`leader` + `specialist` blocks)

**Files:**
- Modify: `federation-game/backend/llm_router.py:497–542` (the `leader` and `specialist` dicts inside `TASK_MODELS`)

- [ ] **Step 1: Locate the `leader` block and verify current values**

```bash
grep -n -A4 '"leader":' federation-game/backend/llm_router.py | head -20
```

Expected output starts with `"leader": {` at line ~498, then `primary:` containing `meta/llama-3.3-70b-instruct`, `max_tokens: 300,`, `timeout: 8,`.

- [ ] **Step 2: Patch the `leader` block (4 numeric edits)**

Edit the four values inside the `leader` block in `TASK_MODELS`:

```python
# Before
"primary": {
    "provider": "nim",
    "model": "meta/llama-3.3-70b-instruct",
    "max_tokens": 300,
    "temperature": 0.85,
    "timeout": 8,            # -> 30
},
"fallback_nim": {
    "provider": "nim",
    "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "max_tokens": 300,
    "temperature": 0.85,
    "timeout": 10,           # -> 30
},
"fallback_openrouter": {
    "provider": "openrouter",
    "model": "meta-llama/llama-3.3-70b-instruct:free",
    "max_tokens": 300,
    "temperature": 0.85,
    "timeout": 12,           # -> 30
},

# After
"primary": {
    "provider": "nim",
    "model": "meta/llama-3.3-70b-instruct",
    "max_tokens": 400,        # 300 -> 400
    "temperature": 0.85,
    "timeout": 30,             # 8 -> 30
},
"fallback_nim": {
    "provider": "nim",
    "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "max_tokens": 300,
    "temperature": 0.85,
    "timeout": 30,             # 10 -> 30
},
"fallback_openrouter": {
    "provider": "openrouter",
    "model": "meta-llama/llama-3.3-70b-instruct:free",
    "max_tokens": 300,
    "temperature": 0.85,
    "timeout": 30,             # 12 -> 30
},
```

- [ ] **Step 3: Patch the `specialist` block (3 numeric edits)**

Same pattern in the `specialist` block — primary `timeout` 6 -> 30, fallback_nim 8 -> 30, fallback_openrouter 10 -> 30. `worker` block below stays at 12s.

- [ ] **Step 4: Verify the changes read correctly**

```bash
grep -nE '"timeout":[[:space:]]+[0-9]+' federation-game/backend/llm_router.py
```

Expected: at least 4 lines showing `30` in the leader and specialist blocks. The `worker` line should still show `12`.

- [ ] **Step 5: Lint the file**

```bash
ruff check federation-game/backend/llm_router.py
```

Expected: exit code 0, no findings.

- [ ] **Step 6: Commit**

```bash
git add federation-game/backend/llm_router.py
git commit -m "fix(p007): bump leader+specialist LLM timeouts to 30s, leader max_tokens to 400

P007 defect A. meta/llama-3.3-70b-instruct measured p50 is ~10s and
observed max is 95s; the previous 6/8/10/12s timeouts caused the chain to
fall back on a majority of leader calls. 30s x3 of p50 and 1/3 of max.
Worker unchanged (uses llama-3.1-8b which is fast enough)."
```

---

## Task 2 — Add failure cooldown constants to `npc_cognition.py`

**Files:**
- Modify: `federation-game/backend/npc_cognition.py` (around line 104)

- [ ] **Step 1: Locate the existing cooldown constants**

```bash
grep -n -E '^(LEADER_COOLDOWN|SPECIALIST_COOLDOWN)' federation-game/backend/npc_cognition.py
```

Expected: two lines, `LEADER_COOLDOWN = 180` near the top (line ~104) and `SPECIALIST_COOLDOWN` shortly below.

- [ ] **Step 2: Insert the failure cooldown constants immediately below `LEADER_COOLDOWN`**

```python
# After this existing line:
LEADER_COOLDOWN = 180  # 3 minutes

# Insert two new lines:
LEADER_COOLDOWN_FAILURE = 600        # 10 min — back off a broken leader path
SPECIALIST_COOLDOWN_FAILURE = 300    #  5 min — back off a broken specialist path
```

`SPECIALIST_COOLDOWN` (already present at line ~102) keeps its current value.

- [ ] **Step 3: Verify**

```bash
grep -n -E '^(LEADER_COOLDOWN|SPECIALIST_COOLDOWN)' federation-game/backend/npc_cognition.py
```

Expected: 4 lines (LEADER_COOLDOWN, LEADER_COOLDOWN_FAILURE, SPECIALIST_COOLDOWN, SPECIALIST_COOLDOWN_FAILURE) in that order.

- [ ] **Step 4: Commit**

```bash
git add federation-game/backend/npc_cognition.py
git commit -m "fix(p007): add LEADER_COOLDOWN_FAILURE and SPECIALIST_COOLDOWN_FAILURE

P007 defect B groundwork. Failure cooldowns are 3.3x and 1.7x the
normal cooldowns respectively, so a broken path gets a real back-off
rather than retrying every tick until world state shifts."
```

---

## Task 3 — Change `_set_cooldown` signature to `(char_id, duration)`

**Files:**
- Modify: `federation-game/backend/npc_cognition.py:379–385`

- [ ] **Step 1: Locate the current function**

```bash
grep -n -A6 '^def _set_cooldown' federation-game/backend/npc_cognition.py
```

Expected: function with body `r.set(f"cognition_cooldown:{char_id}", str(time.time()), ex=600)`.

- [ ] **Step 2: Change the signature and use the explicit duration**

```python
# Before
def _set_cooldown(char_id: str):
    """Mark an NPC as having just had an LLM cognition call."""
    r = _get_redis()
    try:
        r.set(f"cognition_cooldown:{char_id}", str(time.time()), ex=600)
    except Exception:
        pass

# After
def _set_cooldown(char_id: str, duration: int) -> None:
    """Mark an NPC as on cooldown for `duration` seconds.

    Caller passes the right value:
        LEADER_COOLDOWN             (180s) - normal leader gap
        LEADER_COOLDOWN_FAILURE     (600s) - back off a broken leader path
        SPECIALIST_COOLDOWN         (?s)   - normal specialist gap
        SPECIALIST_COOLDOWN_FAILURE (300s) - back off a broken specialist path
    """
    r = _get_redis()
    try:
        r.set(f"cognition_cooldown:{char_id}", str(time.time()), ex=duration)
    except Exception:
        pass
```

- [ ] **Step 3: Search for any other callers**

```bash
grep -rn '_set_cooldown(' federation-game/backend/
```

Expected: ONLY two callsites in `npc_cognition.py`. No external files. **No `routes/pcs.py` exists** — fact-check this; if anything else appears, that's where the next two tasks must extend.

- [ ] **Step 4: Do NOT commit yet**

Signature change breaks both existing callers — Tasks 4 and 5 update them.

---

## Task 4 — Fix leader branch: set cooldown on every path

**Files:**
- Modify: `federation-game/backend/npc_cognition.py` (the leader cognition loop in `run_cognition`, lines ~887–960)

- [ ] **Step 1: Locate the leader branch**

```bash
grep -n -B1 -A4 '^def run_cognition' federation-game/backend/npc_cognition.py
```

Find the `Step 2: Process leaders` block (line ~844) and inside it the `if llm_result["success"]:` block.

- [ ] **Step 2: Add `cooldown_set = False` immediately before the `if llm_result["success"]:` line**

The block to edit currently looks like:

```python
        llm_result = route_call("leader", system_prompt, user_prompt)
        turn_error_code: Optional[str] = None
        llm_calls_this_tick += 1
        result["stats"]["calls_made"] += 1
        result["stats"]["total_latency_ms"] += llm_result.get("latency_ms", 0)

        model_used = llm_result.get("model", "unknown")
        if model_used not in result["stats"]["models_used"]:
            result["stats"]["models_used"][model_used] = 0
        result["stats"]["models_used"][model_used] += 1

        if llm_result["success"]:
```

Insert `cooldown_set = False` between the `result["stats"]["models_used"][model_used] += 1` and the `if llm_result["success"]:` line, then change `if llm_result["success"]:` to leave itself unchanged.

- [ ] **Step 3: Update the success-cooldown call and set the flag**

Find the existing:

```python
                _set_cooldown(cid)
                log_npc_activity(cid, "cognition", {
                    ...
                    "success": True,
                })
            else:
```

Replace with:

```python
                _set_cooldown(cid, LEADER_COOLDOWN)
                log_npc_activity(cid, "cognition", {
                    ...
                    "success": True,
                })
                cooldown_set = True
            else:
```

- [ ] **Step 4: Add the failure-cooldown call after the entire if/else block**

After the existing `else:` branch (ending with `result["errors"].append(...)`) and BEFORE `_log_cognition_turn(cid, "leader", ...)` add:

```python
        if not cooldown_set:
            _set_cooldown(cid, LEADER_COOLDOWN_FAILURE)
```

- [ ] **Step 5: Verify the file parses**

```bash
python -c "import ast; ast.parse(open('federation-game/backend/npc_cognition.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add federation-game/backend/npc_cognition.py
git commit -m "fix(p007): set leader cooldown on LLM failure/parse paths

Old code only called _set_cooldown on the success-and-parsed path,
letting llm_failed and parse_unparseable runs re-attempt every tick
with the same prompt. New code: track cooldown_set, set on failure
with LEADER_COOLDOWN_FAILURE (10min) when the success path skipped."
```

---

## Task 5 — Fix specialist branch with the same pattern

**Files:**
- Modify: `federation-game/backend/npc_cognition.py:995–1062`

- [ ] **Step 1: Locate the specialist branch**

Find the second `for npc in npc_list:` loop in `run_cognition`, with `# Specialists only cognize if triggered` comment.

- [ ] **Step 2: Apply identical edits**

Same pattern: add `cooldown_set = False` before the `if llm_result["success"]:` block; change `_set_cooldown(cid)` to `_set_cooldown(cid, SPECIALIST_COOLDOWN)`; add `cooldown_set = True` after that line; add the failure-cooldown block before `_log_cognition_turn(cid, "specialist", ...)`:

```python
cooldown_set = False                                # NEW
if llm_result["success"]:
    ...
    decision = _parse_llm_response(...)
    if decision:
        ...
        _set_cooldown(cid, SPECIALIST_COOLDON)      # changed
        log_npc_activity(cid, "cognition", {
            ...
            "success": True,
        })
        cooldown_set = True                         # NEW
    else:
        turn_error_code = "parse_unparseable"
        ...
else:
    turn_error_code = "llm_failed"
    ...

if not cooldown_set:                                # NEW
    _set_cooldown(cid, SPECIALIST_COOLDON_FAILURE)

_log_cognition_turn(cid, "specialist", ...)
```

- [ ] **Step 3: Verify the file parses**

```bash
python -c "import ast; ast.parse(open('federation-game/backend/npc_cognition.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Lint**

```bash
ruff check federation-game/backend/npc_cognition.py
```

Expected: exit 0.

- [ ] **Step 5: Confirm callers**

```bash
grep -rn '_set_cooldown(' federation-game/backend/ | grep -v __pycache__
```

Expected: exactly 3 hits. Two callsites inside `npc_cognition.py` (lines ~932 and ~1034) plus the function definition. No matches in `routes/`.

- [ ] **Step 6: Commit**

```bash
git add federation-game/backend/npc_cognition.py
git commit -m "fix(p007): set specialist cooldown on LLM failure/parse paths

Mirrors the leader branch fix. Specialists share the same defect B
but stay less visible because they only cognize when triggered.
With Task 4 + 5, every cognition call now sets a cooldown.

P007 now fully addresses both root causes (defects A and B)."
```

---

## Task 6 — Write `scripts/p007-deploy-check.sh`

**Files:**
- Create: `S:/federation/scripts/p007-deploy-check.sh`

- [ ] **Step 1: Write the file**

```bash
cat > scripts/p007-deploy-check.sh <<'P007_EOF'
#!/usr/bin/env bash
# P007 deploy verification - leader cognition loop fix
#
# Verifies both defect fixes are deployed and that the analyzer no longer
# reports online-flagged leaders 5 minutes after the restart.

set -euo pipefail

SSH_HOST="root@187.77.3.56"
SSH_KEY="${HOME}/.ssh/id_ed25519"
PRIMARY="federation-game-backend-1"

ssh_run() {
  ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_HOST" "$1"
}

# --- Step 1: defect B fix live (failure-cooldown constants present) ---
count=$(ssh_run "docker exec $PRIMARY grep -c LEADER_COOLDOWN_FAILURE /app/npc_cognition.py")
if [ "$count" -eq 0 ]; then
  echo "FAIL: LEADER_COOLDOWN_FAILURE missing from deployed npc_cognition.py"
  exit 1
fi
echo "OK: defect B fix is live (LEADER_COOLDOWN_FAILURE present)"

# --- Step 2: defect A fix live (timeout bumped to 30) ---
count=$(ssh_run "docker exec $PRIMARY grep -cE '\"timeout\": 30' /app/llm_router.py")
if [ "$count" -lt 1 ]; then
  echo "FAIL: TASK_MODELS timeout 30 not found in deployed llm_router.py"
  exit 1
fi
echo "OK: defect A fix is live (timeout=30 in TASK_MODELS)"

# --- Step 3: wait 5 min, then assert 0 online-flagged leaders ---
echo "Waiting 5 minutes for fresh leader cognition turns to accumulate..."
sleep 300

analyze_cmd='python3 -c "import urllib.request as u, json, sys; d=json.loads(u.urlopen(chr(34)+chr(104)+chr(116)+chr(116)+chr(112)+chr(58)+chr(47)+chr(47)+chr(49)+chr(50)+chr(55)+chr(46)+chr(48)+chr(46)+chr(48)+chr(46)+chr(49)+chr(58)+chr(56)+chr(48)+chr(48)+chr(48)+chr(47)+chr(110)+chr(112)+chr(99)+chr(45)+chr(116)+chr(117)+chr(114)+chr(110)+chr(115)+chr(47)+chr(97)+chr(110)+chr(97)+chr(108)+chr(121)+chr(122)+chr(101)+chr(63)+chr(108)+chr(105)+chr(109)+chr(105)+chr(116)+chr(61)+chr(53)+chr(48)+chr(48), timeout=20).read().decode()); flagged=[r for r in d.get(chr(34)+chr(102)+chr(108)+chr(101)+chr(101)+chr(116)+chr(34), []) if r.get(chr(34)+chr(111)+chr(110)+chr(108)+chr(105)+chr(110)+chr(101)+chr(34)) and r.get(chr(34)+chr(97)+chr(110)+chr(111)+chr(109)+chr(97)+chr(108)+chr(105)+chr(101)+chr(115)+chr(34))]; print(len(flagged))"'

hits=$(ssh_run "docker exec $PRIMARY $analyze_cmd")

if [ "$hits" -gt 0 ]; then
  echo "FAIL: $hits leaders still flagged online after fix"
  exit 1
fi

echo "OK: 0 leaders flagged online in 600s window - loop fixed"
P007_EOF
chmod +x scripts/p007-deploy-check.sh
```

- [ ] **Step 2: Smoke-test bash syntax**

```bash
bash -n scripts/p007-deploy-check.sh
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/p007-deploy-check.sh
git commit -m "chore(p007): add deploy verification script

Asserts both defect fixes are deployed, waits 5 min for the worker
to log fresh leader cognition turns, then checks /npc-turns/analyze
for zero online-flagged leaders."
```

---

## Task 7 — Update `.horizon/HORIZON_STATUS.md`

**Files:**
- Modify: `S:/federation/.horizon/HORIZON_STATUS.md`

- [ ] **Step 1: Add P007 to "Completed This Session"**

Add a new bullet:
```markdown
- [x] P007 — Leader cognition retry loop fix — completed
```

- [ ] **Step 2: Add Deploy History row**

Append:
```markdown
| (scp) | P007 Leader cognition retry loop fix | ⏳ pending deploy |
```

- [ ] **Step 3: Commit**

```bash
git add .horizon/HORIZIZON_STATUS.md
git commit -m "docs(horizon): mark P007 plan complete and pending deploy"
```

---

## Deploy (post-plan, manual)

```powershell
scp -i "$env:USERPROFILE\.ssh\id_ed25519" federation-game/backend/llm_router.py root@187.77.3.56:/tmp/
scp -i "$env:USERPROFILE\.ssh\id_ed25519" federation-game/backend/npc_cognition.py root@187.77.3.56:/tmp/

ssh -i "$env:USERPROFILE\.ssh\id_ed25519" root@187.77.3.56 "cp /tmp/llm_router.py /docker/federation-game/backend/ && cp /tmp/npc_cognition.py /docker/federation-game/backend/ && docker exec federation-game-backend-1 find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; docker restart federation-game-backend-1; docker restart federation-game-worker-1"

bash ./scripts/p007-deploy-check.sh
```

---

## Self-Review

**Coverage:** Each of [spec § Fix / Edit 1], [§ Fix / Edit 2], [§ Verification] and [§ Deploy] maps to its own task. No spec requirement has been skipped.

**Type consistency check:** `_set_cooldown(char_id, duration)` introduced in Task 3 is referenced in Tasks 4 and 5 with explicit constants matching Task 2. The `cognition_cooldown:{char_id}` Redis key and `r.set(..., ex=...)` argument shape are preserved across the signature change. `cooldown_set` is a new local variable; it does not collide with any module-level name.

**Spec-vs-plan deviations explicitly logged:**
- Spec stated "5 callers in npc_cognition.py and 1 in routes/pcs.py"; plan uses the verified count of 2 internal callsites and 0 external callsites after a `grep -rn` fact-check.
- Spec referenced `routes/pcs.py`; the file does not exist. Routes file is `routes/npcs.py` and it does not call `_set_cooldown`. Plan correctly skips any task for `routes/`.

**Risk note:** Success-path `cooldown_set = True` placement must be OUTSIDE the try/except wrapping the Redis ZADD on lines 913–929. Plan Step 4 places it after `log_npc_activity(...)` to avoid silent loss on Redis errors.
