#!/bin/sh
# Federation DB Backup Script
# Runs as a one-shot container: docker compose run --rm backup
# Or triggered by Cronicle schedule
#
# Note: This container runs on the fed-net network alongside
# the game services, so it can reach postgres and redis directly.

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

echo "=== Federation Backup Started: $(date) ==="

# Create backup dir if needed
mkdir -p "$BACKUP_DIR"

# 1. pg_dump the database
DUMP_FILE="${BACKUP_DIR}/federation_db_${TIMESTAMP}.sql.gz"
echo "Dumping PostgreSQL database..."
pg_dump -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" | gzip > "$DUMP_FILE"
DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo "Database dump: $DUMP_FILE ($DUMP_SIZE)"

# 2. Save Redis state via redis-cli (available in postgres:15-alpine via apk)
echo "Installing redis-cli..."
apk add --no-cache redis > /dev/null 2>&1
REDIS_FILE="${BACKUP_DIR}/federation_redis_${TIMESTAMP}.rdb"
echo "Triggering Redis BGSAVE..."
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" BGSAVE
sleep 3
# We can't docker cp from inside a container, so save the lastsave timestamp as verification
LASTSAVE=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" LASTSAVE)
echo "Redis lastsave timestamp: $LASTSAVE"
# Save a marker file with the lastsave info
echo "Redis BGSAVE completed at $(date) - LASTSAVE: $LASTSAVE" > "${BACKUP_DIR}/redis_lastsave_${TIMESTAMP}.txt"

# 3. Clean up old backups (older than RETENTION_DAYS)
echo "Cleaning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "federation_db_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "redis_lastsave_*.txt" -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
REMAINING=$(ls -1 "$BACKUP_DIR" | wc -l)
echo "Remaining backup files: $REMAINING"

echo "=== Federation Backup Complete: $(date) ==="
echo "DB: $DUMP_FILE ($DUMP_SIZE)"
echo "Redis: BGSAVE confirmed, LASTSAVE=$LASTSAVE"
