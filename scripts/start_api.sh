#!/bin/bash
# BEarn API Server Launcher (Node.js backend)
# Usage: ./scripts/start_api.sh [port]

PORT=${1:-3000}
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "========================================"
echo "  BEarn API Server"
echo "  Port: $PORT"
echo "========================================"
echo ""

# Load .env if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

cd "$SCRIPT_DIR/server" && npm start
