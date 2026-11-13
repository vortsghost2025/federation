#!/usr/bin/env bash
# Nightly Redis snapshot for Federation (runs on the VPS host via cron).
# Deployed 2026-11-13 as /root/scripts/redis_snapshot.sh with cron:
#   0 3 * * * /root/scripts/redis_snapshot.sh >> /var/log/redis_snapshot.log 2>&1
# BGSAVE is non-blocking (fork), so this is safe anytime - no tick window needed.
# Keeps the newest KEEP dumps as .rdb.gz in BACKUP_DIR.
# NOTE: the VPS already runs an hourly restic backup (/usr/local/bin/federation-backup.sh,
# repos /backups/restic/{postgres,redis,config}, disk guard <8G free). This script adds an
# independent, plain restorable dump that needs no restic password.
# KEEP=7 (not 14) because the host disk sits near the 8G restic guard threshold.
set -euo pipefail

CONTAINER="federation-game-redis-1"
BACKUP_DIR="/docker/federation-game/backups/redis"
KEEP=7
LOG_TAG="redis_snapshot"

mkdir -p "$BACKUP_DIR"
TS="$(date -u +%Y%m%d_%H%M%S)"

# Trigger a background save and wait for it to finish (max ~5 min).
docker exec "$CONTAINER" redis-cli BGSAVE >/dev/null
for i in $(seq 1 60); do
  PROG="$(docker exec "$CONTAINER" redis-cli INFO persistence | tr -d '\r' | awk -F: '$1=="rdb_bgsave_in_progress"{print $2}')"
  [ "$PROG" = "0" ] && break
  sleep 5
done

# Locate the dump inside the container and copy it out.
DIR="$(docker exec "$CONTAINER" redis-cli CONFIG GET dir | tail -1 | tr -d '\r')"
FILE="$(docker exec "$CONTAINER" redis-cli CONFIG GET dbfilename | tail -1 | tr -d '\r')"
SRC="$DIR/$FILE"
TMP="$(mktemp)"
docker cp "$CONTAINER:$SRC" "$TMP"
gzip -c "$TMP" > "$BACKUP_DIR/dump-$TS.rdb.gz"
rm -f "$TMP"

STATUS="$(docker exec "$CONTAINER" redis-cli INFO persistence | tr -d '\r' | awk -F: '$1=="rdb_last_bgsave_status"{print $2}')"
SIZE="$(stat -c%s "$BACKUP_DIR/dump-$TS.rdb.gz")"
echo "$(date -u +%FT%TZ) [$LOG_TAG] dump-$TS.rdb.gz bytes=$SIZE rdb_last_bgsave_status=$STATUS"

# Prune old dumps, keep newest KEEP.
ls -1t "$BACKUP_DIR"/dump-*.rdb.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f --
echo "$(date -u +%FT%TZ) [$LOG_TAG] keeping $(ls -1 "$BACKUP_DIR"/dump-*.rdb.gz 2>/dev/null | wc -l) dumps:"
ls -1t "$BACKUP_DIR"/dump-*.rdb.gz | head -3
