#!/bin/bash
export RESTIC_PASSWORD_FILE=/root/.backup_pass
HOST=srv1345984
RETENTION_DAYS=7
RETENTION_WEEKS=4
RETENTION_MONTHS=12
MIN_FREE_GB=8

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [backup] $1"; }

# Disk guard - if free space falls below threshold, prune aggressively.
FREE_GB=$(df -BG / | awk 'NR==2 {sub("G","",$4); print $4}')
if [ -z "$FREE_GB" ] || [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  log "WARNING: free disk < ${MIN_FREE_GB}G (${FREE_GB}G). Pruning to 2 daily, 1 weekly, 0 monthly."
  for repo in postgres redis config; do
    restic -q -r /backups/restic/$repo --no-cache --password-file $RESTIC_PASSWORD_FILE \
      forget --keep-daily 2 --keep-weekly 1 --prune 2>&1 | tail -1 || log "emergency prune failed for $repo"
  done
fi

# Hourly incremental backup
restic -q backup /var/lib/docker/volumes/federation-game_postgres_data --repo /backups/restic/postgres --host $HOST 2>&1 | tail -1 || log 'postgres backup failed'
restic -q backup /var/lib/docker/volumes/federation-game_redis_data --repo /backups/restic/redis --host $HOST 2>&1 | tail -1 || log 'redis backup failed'
restic -q backup /docker/federation-game --repo /backups/restic/config --host $HOST --exclude='*.git*' --exclude='public_html/simulation.js' 2>&1 | tail -1 || log 'config backup failed'

# Weekly retention prune
if [ $(date +%u) -eq 0 ]; then
    for repo in postgres redis config; do
      restic -q -r /backups/restic/$repo --no-cache --password-file $RESTIC_PASSWORD_FILE \
        forget --host $HOST --keep-daily $RETENTION_DAYS --keep-weekly $RETENTION_WEEKS --prune 2>&1 | tail -2
    done
fi

# Monthly archive
if [ $(date +%d) -eq 1 ]; then
    for repo in postgres redis config; do
      restic -q -r /backups/restic/$repo --no-cache --password-file $RESTIC_PASSWORD_FILE \
        forget --host $HOST --keep-monthly $RETENTION_MONTHS --prune 2>&1 | tail -2
    done
fi

log 'backup run complete'
