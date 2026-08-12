#!/bin/bash
# Tier 3: Circuit Reset wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 circuit_reset.py --check >> /var/log/federation/circuit_reset.log 2>&1
