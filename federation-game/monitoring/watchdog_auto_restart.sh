#!/bin/bash
# Tier 3: Auto Restart wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 auto_restart.py --check >> /var/log/federation/auto_restart.log 2>&1
