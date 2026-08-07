#!/usr/bin/env bash
# Thin wrapper that forwards arguments to the Python CLI module (builder.cli).
# Usage: builder_cli.sh <command> [args]

set -euo pipefail

# Resolve Python interpreter
PYTHON=$(which python3 || which python)

# Ensure the project root is on PYTHONPATH (relative to this script)
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# Execute the module with all arguments
exec "$PYTHON" -m builder.cli "$@"