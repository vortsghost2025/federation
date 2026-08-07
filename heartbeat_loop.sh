#!/bin/bash
# Federation Architect heartbeat loop — runs heartbeat.sh every 5 minutes.

SCRIPT=/docker/federation-architect/heartbeat.sh
while true; do
  "$SCRIPT"
  sleep 300  # 5 minutes
done
