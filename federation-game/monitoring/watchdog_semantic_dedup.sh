#!/bin/bash
# Semantic dedup + outcome feedback monitor wrapper
cd /docker/federation-game/monitoring
/usr/bin/python3 semantic_dedup_monitor.py >> /var/log/federation/semantic_dedup.log 2>&1