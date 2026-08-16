#!/bin/bash
ENV_FILE="/docker/federation-game/.env"
BACKUP=/docker/federation-game/.env.bak-notify-disable-20260622-165651

if [ -z "$BACKUP" ]; then
  exit 0
fi

VAL=
if [ -z "$VAL" ]; then
  RESTORE_LINE=
  if [ -n "$RESTORE_LINE" ]; then
    if grep -q "^NOTIFICATION_URLS=" "$ENV_FILE"; then
      sed -i "s|^NOTIFICATION_URLS=.*|$RESTORE_LINE|" "$ENV_FILE"
    else
      printf "
%s
" "$RESTORE_LINE" >> "$ENV_FILE"
    fi
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [check_notification_env] RESTORED NOTIFICATION_URLS from $BACKUP"
    docker compose -f /docker/federation-game/docker-compose.yml up -d worker >/dev/null 2>&1
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [check_notification_env] Worker recreated to load restored env"
  fi
fi
