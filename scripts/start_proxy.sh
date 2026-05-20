#!/bin/bash
# BEarn Proxy Server Launcher
# Usage: ./scripts/start_proxy.sh [port]

PORT=${1:-8080}
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "========================================"
echo "  BEarn Proxy Server"
echo "  Port: $PORT"
echo "  Rate: \$0.50/GB"
echo "========================================"
echo ""

# Load .env if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

export PROXY_PORT=$PORT

cd "$SCRIPT_DIR" && python3 -m src.proxy_server
