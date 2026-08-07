#!/bin/bash
# Spectator telemetry: take a screenshot every 60s and store under /docker/federation-architect/snapshots/
# Lets Kilo review what's visible without copy-paste.

set -e

OUT=/docker/federation-architect/snapshots
mkdir -p "$OUT"
TOKEN="yNLFi5wxHagt9TMrgoBvWZe8Izzs8ZLe"
URL="https://federation-game.deliberatefederation.cloud/spectator.html"
# Use loopback to bypass Traefik hostname match
URL="https://federation-game.deliberatefederation.cloud/spectator.html"

while true; do
  TS=$(date -u +%FT%T)
  PNG="$OUT/${TS}.png"
  HTTP=$(curl -s -X POST http://127.0.0.1:32769/screenshot \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"$URL\",\"gotoOptions\":{\"waitUntil\":\"networkidle2\",\"timeout\":20000},\"viewport\":{\"width\":1280,\"height\":2400}}" \
    -o "$PNG" -w "%{http_code}")
  SIZE=$(stat -c %s "$PNG" 2>/dev/null || echo 0)
  echo "$TS http=$HTTP size=$SIZE" >> /var/lib/dagu/state/architect/screenshots.log
  # Keep only last 24 snapshots (~24 minutes at 1/min)
  ls -t "$OUT"/*.png 2>/dev/null | tail -n +25 | xargs -r rm
  sleep 60
done
