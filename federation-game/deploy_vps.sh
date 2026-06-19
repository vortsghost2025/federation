#!/usr/bin/env bash
set -euo pipefail

VPS="${VPS:-root@187.77.3.56}"
APP_ROOT="/docker/federation-game"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./deploy_vps.sh check npc-agent [remote_name]
  ./deploy_vps.sh check backend <remote_name>
  ./deploy_vps.sh check backend+worker <remote_name>
  ./deploy_vps.sh npc-agent <local_file> [remote_name]
  ./deploy_vps.sh backend <local_file> <remote_name>
  ./deploy_vps.sh backend+worker <local_file> <remote_name>

Examples:
  ./deploy_vps.sh check npc-agent
  ./deploy_vps.sh check backend npc_messaging.py
  ./deploy_vps.sh check backend+worker worker.py
  ./deploy_vps.sh npc-agent npc-agent/npc_agent.canonical_v2.py
  ./deploy_vps.sh backend backend/npc_messaging.patched.py npc_messaging.py
  ./deploy_vps.sh backend+worker backend/some_shared_file.py some_shared_file.py

Notes:
  - npc-agent updates the VPS host copy and restarts BOTH NPC containers.
  - backend updates the mounted host copy and restarts backend.
  - backend+worker updates host/backend and restarts both.
EOF
}

resolve_local() {
  case "$1" in
    /[A-Za-z]/*|[A-Za-z]:/*|/*)
      printf '%s\n' "$1"
      ;;
    *)
      printf '%s/%s\n' "$SCRIPT_DIR" "$1"
      ;;
  esac
}

remote_compile_if_python() {
  local tmp_path="$1"
  local remote_name="$2"
  if [[ "$remote_name" == *.py ]]; then
    ssh "$VPS" "python3 -m py_compile '$tmp_path'"
  fi
}

backup_and_copy_host() {
  local tmp_path="$1"
  local host_target="$2"
  ssh "$VPS" bash -s -- "$tmp_path" "$host_target" <<'EOF'
set -euo pipefail
TMP_PATH="$1"
HOST_TARGET="$2"
TS="$(date +%Y%m%d_%H%M%S)"
if [ -f "$HOST_TARGET" ]; then
  cp "$HOST_TARGET" "$HOST_TARGET.bak.$TS"
fi
cp "$TMP_PATH" "$HOST_TARGET"
EOF
}

print_md5_block() {
  local label="$1"
  local command="$2"
  printf '\n[%s]\n' "$label"
  ssh "$VPS" "$command"
}

check_mode() {
  local target="$1"
  local remote_name="$2"
  case "$target" in
    npc-agent)
      local host_target="$APP_ROOT/npc-agent/$remote_name"
      print_md5_block "host" "md5sum '$host_target'"
      print_md5_block "container federation-game-npc-agent-001-1" "docker exec federation-game-npc-agent-001-1 md5sum /app/$remote_name"
      print_md5_block "container federation-game-npc-agent-306-1" "docker exec federation-game-npc-agent-306-1 md5sum /app/$remote_name"
      print_md5_block "status" "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'npc-agent-(001|306)'"
      ;;
    backend)
      local host_target="$APP_ROOT/backend/$remote_name"
      print_md5_block "host" "md5sum '$host_target'"
      print_md5_block "container federation-game-backend-1" "docker exec federation-game-backend-1 md5sum /app/$remote_name"
      print_md5_block "status" "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'backend-1'"
      ;;
    backend+worker)
      local host_target="$APP_ROOT/backend/$remote_name"
      print_md5_block "host" "md5sum '$host_target'"
      print_md5_block "container federation-game-backend-1" "docker exec federation-game-backend-1 md5sum /app/$remote_name"
      print_md5_block "container federation-game-worker-1" "docker exec federation-game-worker-1 md5sum /app/$remote_name"
      print_md5_block "status" "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'backend-1|worker-1'"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

if [ "$#" -lt 2 ]; then
  usage
  exit 1
fi

MODE="$1"

if [ "$MODE" = "check" ]; then
  if [ "$#" -lt 2 ]; then
    usage
    exit 1
  fi
  TARGET="$2"
  case "$TARGET" in
    npc-agent)
      check_mode "$TARGET" "${3:-npc_agent.py}"
      ;;
    backend|backend+worker)
      if [ "$#" -lt 3 ]; then
        usage
        exit 1
      fi
      check_mode "$TARGET" "$3"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
  exit 0
fi

LOCAL_FILE_RAW="$2"
LOCAL_FILE="$(resolve_local "$LOCAL_FILE_RAW")"

if [ ! -f "$LOCAL_FILE" ]; then
  echo "Local file not found: $LOCAL_FILE" >&2
  exit 1
fi

case "$MODE" in
  npc-agent)
    REMOTE_NAME="${3:-npc_agent.py}"
    TMP_PATH="/tmp/$REMOTE_NAME"
    HOST_TARGET="$APP_ROOT/npc-agent/$REMOTE_NAME"

    echo "==> Uploading NPC agent file"
    scp "$LOCAL_FILE" "$VPS:$TMP_PATH"
    remote_compile_if_python "$TMP_PATH" "$REMOTE_NAME"
    backup_and_copy_host "$TMP_PATH" "$HOST_TARGET"

    echo "==> Restarting NPC containers"
    ssh "$VPS" "docker restart federation-game-npc-agent-001-1 federation-game-npc-agent-306-1 >/dev/null"
    sleep 3

    print_md5_block "host" "md5sum '$HOST_TARGET'"
    print_md5_block "container federation-game-npc-agent-001-1" "docker exec federation-game-npc-agent-001-1 md5sum /app/$REMOTE_NAME"
    print_md5_block "container federation-game-npc-agent-306-1" "docker exec federation-game-npc-agent-306-1 md5sum /app/$REMOTE_NAME"
    print_md5_block "status" "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'npc-agent-(001|306)'"
    ;;

  backend)
    if [ "$#" -lt 3 ]; then
      usage
      exit 1
    fi
    REMOTE_NAME="$3"
    TMP_PATH="/tmp/$REMOTE_NAME"
    HOST_TARGET="$APP_ROOT/backend/$REMOTE_NAME"

    echo "==> Uploading backend file"
    scp "$LOCAL_FILE" "$VPS:$TMP_PATH"
    remote_compile_if_python "$TMP_PATH" "$REMOTE_NAME"
    backup_and_copy_host "$TMP_PATH" "$HOST_TARGET"

    echo "==> Restarting backend"
    ssh "$VPS" "docker restart federation-game-backend-1 >/dev/null"
    sleep 3

    print_md5_block "host" "md5sum '$HOST_TARGET'"
    print_md5_block "container federation-game-backend-1" "docker exec federation-game-backend-1 md5sum /app/$REMOTE_NAME"
    print_md5_block "status" "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'backend-1'"
    ;;

  backend+worker)
    if [ "$#" -lt 3 ]; then
      usage
      exit 1
    fi
    REMOTE_NAME="$3"
    TMP_PATH="/tmp/$REMOTE_NAME"
    HOST_TARGET="$APP_ROOT/backend/$REMOTE_NAME"

    echo "==> Uploading shared backend/worker file"
    scp "$LOCAL_FILE" "$VPS:$TMP_PATH"
    remote_compile_if_python "$TMP_PATH" "$REMOTE_NAME"
    backup_and_copy_host "$TMP_PATH" "$HOST_TARGET"

    echo "==> Restarting backend and worker"
    ssh "$VPS" "docker restart federation-game-backend-1 federation-game-worker-1 >/dev/null"
    sleep 3

    print_md5_block "host" "md5sum '$HOST_TARGET'"
    print_md5_block "container federation-game-backend-1" "docker exec federation-game-backend-1 md5sum /app/$REMOTE_NAME"
    print_md5_block "container federation-game-worker-1" "docker exec federation-game-worker-1 md5sum /app/$REMOTE_NAME"
    print_md5_block "status" "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'backend-1|worker-1'"
    ;;

  *)
    usage
    exit 1
    ;;
esac
