#!/bin/bash
# Federation Runtime-Truth Watchdog — verifies deployed files are actually live.
# Checks host md5 vs every running-container md5 for all files in the manifest.
# Exit codes: 0 = all clear, 1 = warning (git ahead/behind only), 2 = critical (host/container drift).
# Called by cron on the VPS host, e.g.: */10 * * * * /docker/federation-game/monitoring/watchdog_runtime_truth.sh >> /var/log/federation/watchdog_runtime_truth.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/var/log/federation"
mkdir -p "$LOG_DIR"

echo "=== Runtime-Truth Watchdog $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

python3 "$SCRIPT_DIR/runtime_truth_check.py" --check-git
EXIT_CODE=$?

if [ $EXIT_CODE -eq 2 ]; then
    echo "[CRITICAL] runtime-truth watchdog: host/container drift detected (not live)"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[WARNING] runtime-truth watchdog: git source-of-truth behind"
else
    echo "[OK] runtime-truth watchdog: all live files in sync"
fi

exit $EXIT_CODE