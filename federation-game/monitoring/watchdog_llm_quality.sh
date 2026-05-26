#!/bin/bash
# Tier 2: LLM Quality Monitor wrapper
export REDIS_URL="redis://localhost:6379/0"
cd /docker/federation-game/monitoring
/usr/bin/python3 llm_quality.py --check >> /var/log/federation/llm_quality.log 2>&1
