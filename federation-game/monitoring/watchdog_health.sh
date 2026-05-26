#!/bin/bash
# Tier 2: Health Dashboard wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 health_dashboard.py --check >> /var/log/federation/health_dashboard.log 2>&1
