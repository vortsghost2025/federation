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
