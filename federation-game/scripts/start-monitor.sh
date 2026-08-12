#!/usr/bin/env bash
# Launch the federation-game monitor in a detached tmux session.
# Usage:
#   ./start-monitor.sh              # start in tmux (default 5min interval)
#   ./start-monitor.sh interval=10  # start with 10-minute interval
#   ./start-monitor.sh once         # single check, no tmux
#
# Attach:  tmux attach -t fed-monitor
# Detach:  Ctrl-b d
# Stop:    tmux kill-session -t fed-monitor  (or Ctrl-b : kill-session)
set -euo pipefail
SCRIPT="/docker/federation-game/scripts/federation-game-monitor.sh"
if [ ! -x "$SCRIPT" ]; then
  chmod +x "$SCRIPT"
fi
SESSION="fed-monitor"
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already running. Attach with: tmux attach -t $SESSION"
  echo "To restart: tmux kill-session -t $SESSION && $0 $*"
  exit 1
fi
if [ "${1:-}" = "once" ]; then
  echo "Running single check (no tmux)..."
  "$SCRIPT" once
  exit 0
fi
echo "Starting monitor in tmux session '$SESSION' (interval=${interval:-5}m)..."
tmux new-session -d -s "$SESSION" -x 200 -y 50 \
  "cd /docker/federation-game && $SCRIPT interval=${interval:-5} 2>&1 | tee -a /docker/federation-game/logs/monitor.log; echo 'Monitor stopped. Press Enter to close.'; read"
echo "Session started. Attach with: tmux attach -t $SESSION"
echo "Log file: /docker/federation-game/logs/monitor.log"
