#!/bin/bash
# Tier 2: Live Narrator Monitor wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 live_narrator.py --check >> /var/log/federation/live_narrator.log 2>&1
