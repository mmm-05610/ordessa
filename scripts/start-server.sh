#!/usr/bin/env bash
# Start the Ordessa Server from the monorepo layout on a loopback high port
# with a throwaway data root. Used for smoke verification; never touches a
# real data directory and never calls a model.
#
# Usage: start-server.sh [port]   (default: 8931; binds 127.0.0.1 only)
set -euo pipefail

PORT=${1:-8931}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TREE=$(cd "$HERE/.." && pwd)
DATA_ROOT=$(mktemp -d /tmp/ordessa-server-smoke.XXXXXX)/data-root  # the server creates and owns the dir itself

export AGENT_BOX_HOME=$DATA_ROOT
export PYTHONPATH="$TREE/packages/backend/pacthold/src:$TREE/plugins/harness/src:$TREE/apps/server/src${PYTHONPATH:+:$PYTHONPATH}"

echo "AGENT_BOX_HOME=$DATA_ROOT"
echo "starting ordessa_server on 127.0.0.1:$PORT"
cd "$TREE/apps/server/src"
trap 'rm -rf "$(dirname "$DATA_ROOT")"' EXIT
exec python3 -m ordessa_server --data-root "$DATA_ROOT" --port "$PORT"
