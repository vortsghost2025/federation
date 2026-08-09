#!/bin/bash
# Goal progress + novelty tracker wrapper
cd /docker/federation-game/monitoring
/usr/bin/python3 goal_progress_monitor.py >> /var/log/federation/goal_progress.log 2>&1