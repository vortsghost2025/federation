#!/bin/bash
# Federation LLM Health Monitor — runs every 5 minutes
# Checks: circuit breakers, error rates, Ollama reachability
# Called by cron: */5 * * * * /docker/federation-game/monitoring/watchdog_llm.sh >> /var/log/federation/watchdog_llm.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/var/log/federation"
mkdir -p "$LOG_DIR"

echo "=== LLM Health Monitor $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Run the LLM check
python3 "$SCRIPT_DIR/monitor.py" --check llm
EXIT_CODE=$?

# Log exit code for downstream alerting
if [ $EXIT_CODE -eq 2 ]; then
    echo "[CRITICAL] LLM monitor detected critical issue"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "[WARNING] LLM monitor detected warning"
else
    echo "[OK] LLM monitor all clear"
fi

exit $EXIT_CODE
