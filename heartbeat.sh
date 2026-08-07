#!/bin/bash
# Federation Architect Loop Heartbeat
# Runs every 5 minutes; scans for new packets, updates markers.

set -e

ARCH=/docker/federation-architect
DAGU_STATE=/var/lib/dagu/state/architect
LOGFILE=$DAGU_STATE/heartbeat.log
MARKER=$DAGU_STATE/last_run
COUNT_FILE=$DAGU_STATE/last_packet_count
AREAS_FILE=$DAGU_STATE/last_areas
ALIVE_FILE=$DAGU_STATE/last_pair_activity

mkdir -p "$DAGU_STATE"
echo "$(date -u +%FT%TZ) heartbeat start" >> "$LOGFILE"

# 1. Run monitor
python3 "$ARCH/monitor.py" >> "$LOGFILE" 2>&1
echo "$(date -u +%FT%TZ) monitor ok" >> "$LOGFILE"

# 2. Count packets and detect new
LAST=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
NOW=$(ls "$ARCH/requests/" 2>/dev/null | wc -l)
echo $NOW > "$COUNT_FILE"
echo "$(date -u +%FT%TZ) packets last=$LAST now=$NOW delta=$((NOW - LAST))" >> "$LOGFILE"
if [ "$NOW" -gt "$LAST" ]; then
  echo "$(date -u +%FT%TZ) NEW_PACKETS=$((NOW - LAST))" >> "$LOGFILE"
  # Latest packet id
  ls -t "$ARCH/requests/" | head -1 >> "$LOGFILE"
fi

# 3. Areas count
COUNT=$(docker exec federation-game-backend-1 python3 -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://127.0.0.1:8000/councilor/areas', timeout=10).read())
print(d['count'])
" 2>/dev/null || echo "ERR")
echo $COUNT > "$AREAS_FILE"
echo "$(date -u +%FT%TZ) areas=$COUNT" >> "$LOGFILE"

# 4. Pair activity in last 10 minutes
for cid in char_001 char_306; do
  D=$(docker logs federation-game-npc-agent-${cid#char_}-1 --since 10m 2>&1 | grep -c "Decision:" || echo 0)
  echo "$(date -u +%FT%TZ) $cid decisions last 10m: $D" >> "$LOGFILE"
done

# 5. Marker
date -u +%FT%TZ > "$MARKER"
echo "$(date -u +%FT%TZ) heartbeat end" >> "$LOGFILE"
