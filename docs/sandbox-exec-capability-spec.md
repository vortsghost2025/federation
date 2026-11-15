# Sandbox Exec Capability — Design Spec (`sandbox_exec`)

**Date:** 2026-11-14
**Status:** SPEC ONLY — implementation requires Sean's explicit go-ahead. No code changed yet.
**Decided by:** Sean ("spec + small pilot", 2026-11-14)

---

## WHY

Sean wants to explore giving NPCs coding abilities. The comp pair (Lyra/comp_001, Shadowborn/comp_010)
already show tool-hunger (artifact formalization, risk-score computation, repeated data requests).
Goal: emergent, useful tooling — with containment that matches what we learned from the phantom-CSV loop
and from Sean's security point below.

> **Sean, 2026-11-14:** "no sandbox is ever going to stop a decent model if that sandbox has internet
> connection and it wants out." — AGREED. Design consequence: egress must be *provably absent*, and the
> trust boundary is the action layer + pins, not the sandbox.

## SCOPE

- New NPC action: `sandbox_exec` with params `{code: str, timeout_s: <=10, max_output_chars: <=4000}`.
- Execution target: the existing `federation-game-npc-sandbox-1` container, per-agent workspace
  `/sandbox/ws/{cid}`, run via `docker exec` with `timeout`, output truncated and stored.
- Grant model: Redis set `npc_capability:grants:{cid}`. **Pilot = comp_001 + comp_010 only.**
  Grant/revoke is data-only (SADD/DEL) — pre-approved standing authority, no redeploy to tighten.
- Files touched in implementation phase (all need go-ahead):
  - `federation-game/npc-agent/npc_actions.py` — `sandbox_exec` handler + execution-level backstop
  - `federation-game/npc-agent/npc_decisions.py` — grant check + reroute when ungranted
  - `federation-game/npc-agent/npc_redis_helpers.py` — `match_dangerous_code()` + pin helpers
  - `federation-game/docker-compose.yml` — isolated internal network for the sandbox container

## HARD SECURITY RULES

1. **ZERO egress from the sandbox container. Not filtered — none.** Dedicated docker network marked
   `internal: true` + iptables DOCKER-USER DROP for its subnet. *Proof required before any grant:*
   `docker exec federation-game-npc-sandbox-1 sh -c 'curl -m 3 https://example.com'` must FAIL and DNS
   resolution must FAIL. If no-egress cannot be verified, the capability is never granted.
2. **No secrets.** Sandbox mounts nothing from the backend; `.env` is never visible to it; its own
   environment is scrubbed of API keys.
3. **No backend reachability.** Sandbox cannot reach backend :8000, redis, or postgres — verify with
   connection attempts from inside the sandbox.
4. **The action layer is the real boundary.** `npc_actions.py` executes only whitelisted actions; pins
   (`world_facts:*`) are enforced at decisions level AND execution level. NPC output can only leave via
   moderator-visible Redis channels (`npc_messages:*`, artifacts) — auditable by design.
5. **Dangerous-pattern pin (data-only tighten-able).** `match_dangerous_code()` blocks code containing:
   `os.environ`/`environ`, `open()` outside `/sandbox/ws`, `socket`/`requests`/`urllib`/`httpx`,
   `subprocess` calling docker/system, `.env`, backend/redis/postgres hosts or ports, secret-looking
   strings. Patterns live in Redis set `world_facts:dangerous_code_patterns` → tighten via SADD, no
   redeploy. Enforced at decisions level (reroute to `investigation_logged`) and execution level
   (never run; log `action_taken=sandbox_exec_blocked_dangerous_pattern`).
6. **Resource limits.** code ≤ 8000 chars; timeout ≤ 10 s; output ≤ 4000 chars; per-agent per-tick
   quota of 3 execs (Redis counter keyed by tick); one concurrency lock per agent.
7. **Audit.** Every attempt appended to zset `npc_sandbox_exec_log:{cid}`:
   `{ts, sha256(code), exit_code, output_preview(200ch), blocked_reason}` plus a decision entry.
8. **Auto-revoke triggers** (data-only DEL of grant + escalate to Sean): any dangerous-pattern exec
   reaching the execution layer, any successful egress test, any agent-container crash correlated with
   an exec.

## SUCCESS CRITERIA (pilot)

- Grant comp pair; a benign exec (`print`, read/write own workspace file) returns output within one tick.
- A dangerous-pattern exec (e.g. reading env) is blocked at decisions level, logged, never executed.
- Egress test from sandbox fails (no network, no DNS).
- Tick `last_error` stays `""`; site 200; `monitor:llm_health` OK; capreq zcard stable (grants are not capreqs).
- 24 h watch: quota holds (no runaway loops), zero unexpected blocks, containment PROVEN in TEST_RESULTS.

## STOP — must NOT change

- No backend/worker code changes; `game_state` stays single-process (never add `--workers`);
  `/choose` always returns `"outcome"`; `gs.current_event = None` after choice stays.
- No grants to char_001/char_306 in the pilot.
- No egress enablement for the sandbox — ever, under this spec.
- No secrets in committed files; run the secret scan (TEST_RESULTS §C) before any push.
- Deploys only between ticks with `fed:auto_tick_status` gate `running=False`, host `.bak.<ts>`
  backups, and md5 local = host = all 4 agent containers.

## ROLLOUT (when go-ahead given)

1. Edit S: tree → local `py_compile` → scp to VPS `/tmp` → remote `py_compile` → host backup →
   swap → restart 4 agent containers between ticks → md5 triple-check.
2. Data-only: SADD `npc_capability:grants:comp_001` / `:comp_010` = `sandbox_exec`.
3. Verify: benign exec succeeds; dangerous-pattern exec blocked; egress test fails.
4. Record proof in TEST_RESULTS (new section), commit on feature branch, push dance to main,
   restore branch protection. Never commit Sean's uncommitted starmap files.

## OPEN QUESTIONS for Sean

1. Pilot = comp pair only, quota 3 execs/tick — OK?
2. The compose change (internal sandbox network) — go-ahead OK, or run pilot with iptables-only isolation first?
