#!/bin/bash
# Tier 3: Fallback Recovery wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 fallback_recovery.py --check >> /var/log/federation/fallback_recovery.log 2>&1
