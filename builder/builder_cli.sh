#!/usr/bin/env bash
# Simple CLI wrapper for the Federation Builder Agent state
# Usage:
#   builder_cli.sh status
#   builder_cli.sh list-pending
#   builder_cli.sh approve <draft_id> <by>
#   builder_cli.sh reject <draft_id> <by> <reason>

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON=$(which python3 || which python)

# Resolve the path to the builder Python module (relative to this script)
PY_MOD="builder.cli"

case "$1" in
    status)
        $PYTHON - <<PY
import json, sys, os
sys.path.append('/docker/federation-architect')
from builder.state import BuilderState
state = BuilderState('/docker/federation-architect/builder/state.json')
print(json.dumps({"stats": state.stats()}, indent=2))
PY
        ;;
    list-pending)
        $PYTHON - <<PY
import json
from builder.state import BuilderState
state = BuilderState('/docker/federation-architect/builder/state.json')
print(json.dumps(state.pending(), indent=2))
PY
        ;;
    approve)
        if [ "$#" -lt 3 ]; then echo "Usage: $0 approve <draft_id> <by>"; exit 1; fi
        DRAFT_ID="$2"
        BY="${3:-"unknown"}"
        $PYTHON - <<PY
import json, sys, os
sys.path.append('/docker/federation-architect')
from builder.state import BuilderState
state = BuilderState('/docker/federation-architect/builder/state.json')
ok = state.approve('$DRAFT_ID', '$BY')
print(json.dumps({"approved": ok, "id": '$DRAFT_ID'}))
PY
        ;;
    reject)
        if [ "$#" -lt 4 ]; then echo "Usage: $0 reject <draft_id> <by> <reason>"; exit 1; fi
        DRAFT_ID="$2"
        BY="$3"
        REASON="$4"
        $PYTHON - <<PY
import json, sys, os
sys.path.append('/docker/federation-architect')
from builder.state import BuilderState
state = BuilderState('/docker/federation-architect/builder/state.json')
ok = state.reject('$DRAFT_ID', '$REASON', '$BY')
print(json.dumps({"rejected": ok, "id": '$DRAFT_ID'}))
PY
        ;;
    show-state)
        if [ "$#" -lt 2 ]; then echo "Usage: $0 show-state <char_id>"; exit 1; fi
        CHAR="$2"
        echo "=== Cognition ==="
        docker exec federation-game-redis-1 redis-cli hgetall "npc_cognition:${CHAR}"
        echo "=== Latest Decision ==="
        docker exec federation-game-redis-1 redis-cli zrevrange "npc_decisions:${CHAR}" 0 0 | head -1
        ;;
    show-cognition)
        if [ "$#" -lt 2 ]; then echo "Usage: $0 show-cognition <char_id>"; exit 1; fi
        CHAR="$2"
        # Use redis discovery to fetch cognition hash
        docker exec federation-game-redis-1 redis-cli hgetall "npc_cognition:${CHAR}"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Commands: status, list-pending, approve, reject, show-cognition, show-state"
        exit 1
        ;;
 esac
