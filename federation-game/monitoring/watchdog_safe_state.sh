#!/bin/bash
# Tier 3: Safe State Verifier wrapper
export REDIS_URL="redis://localhost:6379/0"
# Backend is reachable from the VPS host via the published docker-proxy port.
# Do NOT hardcode container IPs (172.26.0.11 went stale); allow env override.
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
cd /docker/federation-game/monitoring
/usr/bin/python3 safe_state.py --check >> /var/log/federation/safe_state.log 2>&1
