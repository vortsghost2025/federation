#!/usr/bin/env bash
# fed-state.sh — Federation session-startup probe.
#
# Captures current state of the federation project in <3 seconds, formatted
# for an LLM to ingest on session start. Replaces the 6-step manual probe
# (git log -> specs -> horizon -> dirty tree -> vps health -> analyzer).
#
# Usage:
#   bash scripts/fed-state.sh
#   bash scripts/fed-state.sh --vps     # include VPS probes (slower, ~10s)
#   bash scripts/fed-state.sh --json    # machine-readable output (todo)
#
# Designed to be invoked at the start of any federation-related session
# to recover state after context loss (compaction, new conversation,
# different agent, etc).

set -euo pipefail

VPS=0
for arg in "$@"; do
  case "$arg" in
    --vps) VPS=1 ;;
    *) ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

echo "=== FEDERATION SESSION STATE ==="
echo "Root: $REPO_ROOT"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

echo "--- HEAD (last 5 commits) ---"
git log --oneline -5 2>/dev/null || echo "  (no git history)"
echo

echo "--- Active specs/plans ---"
if [ -d docs/superpowers/specs ]; then
  ls -1 docs/superpowers/specs/ 2>/dev/null | tail -5 | sed 's/^/  spec: /'
fi
if [ -d docs/superpowers/plans ]; then
  ls -1 docs/superpowers/plans/ 2>/dev/null | tail -5 | sed 's/^/  plan: /'
fi
echo

echo "--- HORIZON status (completed items) ---"
grep -E "^- \[" .horizon/HORIZON_STATUS.md 2>/dev/null | tail -10 || echo "  (no horizon file)"
echo

echo "--- Dirty tree summary ---"
dirty=$(git status --porcelain 2>/dev/null | wc -l)
untracked=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
echo "  modified: $dirty,  untracked: $untracked"
if [ "$dirty" -gt 0 ] && [ "$dirty" -lt 30 ]; then
  git status --porcelain 2>/dev/null | head -10 | sed 's/^/  /'
elif [ "$dirty" -ge 30 ]; then
  echo "  (truncated, run \`git status\` for full list)"
fi
echo

  if [ "$VPS" -eq 1 ]; then
  echo "--- VPS container health ---"
  SSH_HOST="root@187.77.3.56"
  SSH_KEY="${HOME}/.ssh/id_ed25519"
  if [ ! -f "$SSH_KEY" ]; then
    # Try the WSL/Cygwin path translation for Windows-side ssh key
    if [ -f "/mnt/c/Users/seand/.ssh/id_ed25519" ]; then
      SSH_KEY="/mnt/c/Users/seand/.ssh/id_ed25519"
    elif [ -f "C:/Users/seand/.ssh/id_ed25519" ]; then
      SSH_KEY="C:/Users/seand/.ssh/id_ed25519"
    fi
  fi

  # When run from WSL/Cygwin, the key file's Windows perms show as 0777.
  # OpenSSH refuses such keys. Copy to a tmp path and chmod 600.
  if [ "${SSH_KEY}" = "/mnt/c/Users/seand/.ssh/id_ed25519" ]; then
    SSH_KEY="/tmp/fed-state-key"
    cp "/mnt/c/Users/seand/.ssh/id_ed25519" "$SSH_KEY" 2>/dev/null
    chmod 600 "$SSH_KEY" 2>/dev/null
  fi

  SSH_BASE=(-i "$SSH_KEY" -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o ServerAliveInterval=2)

  echo "  federation containers (Up/Restarting/Exited):"
  timeout 6 ssh "${SSH_BASE[@]}" "$SSH_HOST" "docker ps -a --filter name=federation --format 'table {{.Names}}\\t{{.Status}}'" 2>&1 | sed 's/^/    /' | head -8
  echo

  # Redis summary
  echo "  Redis summary:"
  REDIS_CMD='docker exec federation-game-backend-1 python3 -c "import redis,json;r=redis.Redis(host=\"redis\",port=6379,db=0,decode_responses=True);prefixes=[\"msg:\",\"session_log:\",\"workflow:\",\"npc:\",\"councilor:\",\"world_state\",\"institution:\",\"role:\",\"npc_artifact:\",\"circuit_breaker:\"];counts={p:sum(1 for _ in r.scan_iter(p+\"*\")) for p in prefixes};total=r.dbsize();leaks=0;[None for k in list(r.scan_iter(\"msg:*\"))[:200] if r.type(k)==\"hash\" and any(p in (r.hget(k,\"body\")or\"\").lower() for p in [\"simulation\",\"substrate\",\"computational\",\"digital\",\"virtual\",\"algorithm\"])];print(json.dumps({\"total\":total,\"prefix_counts\":{k:v for k,v in counts.items() if v>0}}))"'
  redis_result=$(timeout 10 ssh "${SSH_BASE[@]}" "$SSH_HOST" "$REDIS_CMD" 2>&1 || echo '{"error":"timeout"}')
  echo "    $redis_result"
  echo
fi

echo
echo "=== End ==="
