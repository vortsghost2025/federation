#!/bin/bash
# Tier 3: Safe State Verifier wrapper
export REDIS_URL="redis://localhost:6379/0"
export BACKEND_URL="http://172.26.0.11:8000"
cd /docker/federation-game/monitoring
/usr/bin/python3 safe_state.py --check >> /var/log/federation/safe_state.log 2>&1
