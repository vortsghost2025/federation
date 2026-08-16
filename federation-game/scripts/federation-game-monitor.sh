#!/usr/bin/env bash
# federation-game-monitor.sh — tmux background monitor for the NPC pair simulation.
#
# Usage:
#   ./federation-game-monitor.sh              # start infinite loop (tmux)
#   ./federation-game-monitor.sh once         # single check, then exit
#   ./federation-game-monitor.sh interval=10  # loop every 10 minutes
#
# Logs: /docker/federation-game/logs/monitor.log  (auto-rotated at 1MB)
#
# Requirements:
#   - kilo CLI (v7.3.16+)
#   - docker, redis-cli, curl, jq
#   - NPC containers running on the VPS
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
INTERVAL="${interval:-5}"          # minutes between checks
LOG_DIR="/docker/federation-game/logs"
LOG_FILE="$LOG_DIR/monitor.log"
MAX_LOG_BYTES=$((1024 * 1024))     # 1 MB rotation
KILO_MODEL="${KILO_MODEL:-kilo/kilo-auto/free}"
KILO_TIMEOUT=120                   # seconds per Kilo invocation
MAX_BACKOFF=30                     # cap sleep after repeated failures
REDIS="docker exec federation-game-redis-1 redis-cli"
STATE_KEY="npc_pair:char_001__char_306:state"
# ── Setup ───────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
log() {
  local ts
  ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  echo "[$ts] $*" | tee -a "$LOG_FILE"
}
rotate_log() {
  if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)" -gt "$MAX_LOG_BYTES" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.1"
    log "(log rotated)"
  fi
}
gather_state() {
  # ── Pair state ──
  local pair_raw
  pair_raw=$($REDIS HGET "$STATE_KEY" convergence_state 2>/dev/null || echo '{}')
  local shared_goal open_question resolved plateau next_q version
  shared_goal=$($REDIS HGET "$STATE_KEY" shared_goal 2>/dev/null || echo "")
  open_question=$($REDIS HGET "$STATE_KEY" open_question 2>/dev/null || echo "")
  resolved=$(echo "$pair_raw" | python3 -c "import sys,json; print(json.load(sys.stdin).get('resolved','?'))" 2>/dev/null || echo "?")
  plateau=$(echo "$pair_raw" | python3 -c "import sys,json; print(json.load(sys.stdin).get('plateau_count','?'))" 2>/dev/null || echo "?")
  next_q=$(echo "$pair_raw" | python3 -c "import sys,json; print(json.load(sys.stdin).get('next_question','')[:120])" 2>/dev/null || echo "")
  version=$(echo "$pair_raw" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
  # ── Recent decisions ──
  local d001 d306
  d001=$($REDIS ZREVRANGE npc_decisions:char_001 0 9 WITHSCORES 2>/dev/null || echo "")
  d306=$($REDIS ZREVRANGE npc_decisions:char_306 0 9 WITHSCORES 2>/dev/null || echo "")
  # ── Recent artifacts ──
  local a001 a306
  a001=$($REDIS LRANGE npc_artifacts:char_001 -5 -1 2>/dev/null || echo "")
  a306=$($REDIS LRANGE npc_artifacts:char_306 -5 -1 2>/dev/null || echo "")
  # ── Recent errors ──
  local errors
  errors=$(docker logs federation-game-backend-1 --tail 50 2>&1 | grep -iE 'ERROR|Traceback|NameError|WRONGTYPE|timeout' | tail -5 || echo "none")
  # ── Ollama health ──
  local ollama_ok ollama_model
  ollama_ok=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://100.95.92.117:11434/api/tags 2>/dev/null || echo "unreachable")
  ollama_model=$(curl -s --max-time 5 http://100.95.92.117:11434/api/tags 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('models',[{}])[0].get('name','?'))" 2>/dev/null || echo "?")
  # ── Completed goals ──
  local completed
  completed=$($REDIS LRANGE "npc_pair:${STATE_KEY##*:}:completed_goals" 0 -1 2>/dev/null | wc -l || echo "0")
  # ── Format prompt ──
  cat <<PROMPT
You are the simulation monitor for the Federation Game NPC pair (char_001 / char_306).
Analyze the current state and produce a SHORT structured report.
Be concise — this runs every $INTERVAL minutes.

## PAIR STATE
shared_goal: $shared_goal
open_question: $open_question
resolved: $resolved | plateau: $plateau | version: $version
next_question: $next_q

## RECENT DECISIONS char_001 (last 10)
$(echo "$d001" | python3 -c "
import sys,json,datetime
lines=[l.strip() for l in sys.stdin if l.strip()]
for i in range(0,len(lines),2):
  d=json.loads(lines[i]); ts=float(lines[i+1])
  print(datetime.datetime.fromtimestamp(ts).strftime('%H:%M'), d.get('category'), '->', d.get('action_taken','')[:40])
" 2>/dev/null || echo "(parse error)")

## RECENT DECISIONS char_306 (last 10)
$(echo "$d306" | python3 -c "
import sys,json,datetime
lines=[l.strip() for l in sys.stdin if l.strip()]
for i in range(0,len(lines),2):
  d=json.loads(lines[i]); ts=float(lines[i+1])
  print(datetime.datetime.fromtimestamp(ts).strftime('%H:%M'), d.get('category'), '->', d.get('action_taken','')[:40])
" 2>/dev/null || echo "(parse error)")

## RECENT ARTIFACTS char_001 (last 5)
$(echo "$a001" | python3 -c "
import sys,json
for l in sys.stdin:
  try:
    d=json.loads(l.strip())
    print(' -', d.get('artifact_type','?'), ':', (d.get('title','?') or d.get('content','?'))[:80])
  except: pass
" 2>/dev/null || echo "(none)")

## RECENT ARTIFACTS char_306 (last 5)
$(echo "$a306" | python3 -c "
import sys,json
for l in sys.stdin:
  try:
    d=json.loads(l.strip())
    print(' -', d.get('artifact_type','?'), ':', (d.get('title','?') or d.get('content','?'))[:80])
  except: pass
" 2>/dev/null || echo "(none)")

## RECENT BACKEND ERRORS
$(echo "$errors" | head -5)

## OLLAMA (local RTX 5060)
reachability: HTTP $ollama_ok | model: $ollama_model

## COMPLETED GOALS LEDGER
entries: $completed

## YOUR TASK
Give a SHORT structured report:
1. Status: healthy / degraded / broken
2. Key accomplishment(s) since last check
3. Concerns (if any)
4. Recommended actions (if any — be specific, actionable)
5. One-line summary

Keep it under 200 words total.
PROMPT
}
run_kilo() {
  local prompt
  prompt=$(gather_state)
  log "─── Kilo monitor check ───"
  # Run Kilo non-interactively; capture stdout+stderr
  local output
  if output=$(timeout "$KILO_TIMEOUT" kilo run --pure --model "$KILO_MODEL" "$prompt" 2>&1); then
    log "$output"
    echo "$output" >> "$LOG_FILE"
    return 0
  else
    local rc=$?
    log "WARNING: Kilo exited $rc ($output)"
    return $rc
  fi
}
# ── Main loop ────────────────────────────────────────────────────────
rotate_log
log "Monitor started (interval=${INTERVAL}m, model=${KILO_MODEL})"
if [ "${1:-}" = "once" ]; then
  log "Running single check..."
  run_kilo || true
  log "Single check complete."
  exit 0
fi
failures=0
while true; do
  if run_kilo; then
    failures=0
  else
    failures=$((failures + 1))
    local backoff=$(( INTERVAL < MAX_BACKOFF ? INTERVAL : MAX_BACKOFF ))
    backoff=$(( backoff * (1 + failures) ))
    log "Backing off ${backoff}m after $failures consecutive failure(s)"
    sleep $((backoff * 60))
    continue
  fi
  log "Next check in ${INTERVAL}m"
  sleep $((INTERVAL * 60))
done
