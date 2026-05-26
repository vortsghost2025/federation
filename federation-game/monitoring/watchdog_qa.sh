#!/bin/bash
# Tier 2: QA Monitor wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 qa_monitor.py --check >> /var/log/federation/qa_monitor.log 2>&1
