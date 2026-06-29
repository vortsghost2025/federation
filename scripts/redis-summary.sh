#!/usr/bin/env bash
# redis-summary.sh — Redis state overview for Federation
#
# Shows key counts by prefix, inbox depths, recent message timestamps,
# and a fourth-wall leak scan. Designed to be run via SSH or locally
# inside the Docker network.
#
# Usage:
#   bash scripts/redis-summary.sh          # local (needs redis-cli)
#   bash scripts/redis-summary.sh --vps    # run on VPS via SSH
#
# Output is LLM-friendly — compact, structured, no color codes.

set -euo pipefail

VPS=0
for arg in "$@"; do
  case "$arg" in
    --vps) VPS=1 ;;
    *) ;;
  esac
done

SSH_HOST="root@187.77.3.56"
SSH_KEY="${HOME}/.ssh/id_ed25519"
if [ ! -f "$SSH_KEY" ]; then
  if [ -f "/mnt/c/Users/seand/.ssh/id_ed25519" ]; then
    SSH_KEY="/mnt/c/Users/seand/.ssh/id_ed25519"
    TMP_KEY="/tmp/fed-redis-key"
    cp "$SSH_KEY" "$TMP_KEY" 2>/dev/null
    chmod 600 "$TMP_KEY" 2>/dev/null
    SSH_KEY="$TMP_KEY"
  fi
fi

SSH_OPTS=(-i "$SSH_KEY" -o ConnectTimeout=8 -o StrictHostKeyChecking=no)

# Redis commands to run (works inside backend container via docker exec)
REDIS_CMD='docker exec federation-game-backend-1 python3 -c "
import redis, json, sys
r = redis.Redis(host=\"redis\", port=6379, db=0, decode_responses=True)

# Key counts by prefix
prefixes = [\"msg:\", \"session_log:\", \"workflow:\", \"npc:\",
            \"npc_decision_bias:\", \"councilor:\", \"world_state\",
            \"institution:\", \"role:\", \"circuit_breaker:\",
            \"npc_artifact:\", \"gemini_\"]
counts = {}
for p in prefixes:
    try:
        n = len(list(r.scan_iter(p + \"*\")))
        if n > 0:
            counts[p] = n
    except:
        pass

# Total keys
total = r.dbsize()

# Inbox depths (top 10 by length)
inbox_depths = {}
for key in r.scan_iter(\"msg:*\"):
    try:
        parts = key.split(\":\")
        if len(parts) >= 3:
            char_id = parts[1]
            inbox_depths.setdefault(char_id, 0)
            inbox_depths[char_id] += 1
    except:
        pass

# Recent messages (newest 3)
recent = []
for key in list(r.scan_iter(\"msg:*\"))[:5]:
    try:
        ts = r.hget(key, \"timestamp\") or \"unknown\"
        recent.append({\"key\": key, \"ts\": ts})
    except:
        pass

# Fourth-wall leak scan
dirty_patterns = [\"simulation\", \"substrate\", \"computational\", \"digital\",
                 \"virtual\", \"algorithm\", \"program\", \"code\",
                 \"debug\", \"error\", \"stack trace\", \"python\",
                 \"import \", \"def \", \"class \", \"TODO\"]
leaks = []
for key in list(r.scan_iter(\"msg:*\"))[:100]:
    try:
        body = r.hget(key, \"body\") or \"\"
        reasoning = r.hget(key, \"reasoning\") or \"\"
        combined = (body + \" \" + reasoning).lower()
        for pat in dirty_patterns:
            if pat.lower() in combined:
                leaks.append({\"key\": key, \"pattern\": pat})
                break
    except:
        pass

# Session log leak scan
session_leaks = 0
for key in list(r.scan_iter(\"session_log:*\"))[:20]:
    try:
        data = r.lrange(key, 0, -1)
        for entry in data:
            el = entry.lower()
            for pat in dirty_patterns:
                if pat.lower() in el:
                    session_leaks += 1
                    break
    except:
        pass

out = {
    \"total_keys\": total,
    \"prefix_counts\": counts,
    \"inbox_depths\": dict(sorted(inbox_depths.items(), key=lambda x: -x[1])[:10]),
    \"recent_messages\": recent[:3],
    \"msg_leaks_found\": len(leaks),
    \"msg_leak_samples\": leaks[:3],
    \"session_log_leaks\": session_leaks,
}
print(json.dumps(out, indent=2))
"'

if [ "$VPS" -eq 1 ]; then
  result=$(timeout 15 ssh "${SSH_OPTS[@]}" "$SSH_HOST" "$REDIS_CMD" 2>&1)
else
  result=$(eval "$REDIS_CMD" 2>&1)
fi

echo "=== FEDERATION REDIS SUMMARY ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo
echo "$result"
echo
echo "=== End ==="
