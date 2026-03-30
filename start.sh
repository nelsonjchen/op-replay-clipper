#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "  OP Replay Clipper"
echo "  http://localhost:7860"
echo "  Press Ctrl+C to stop"
echo ""

# Auto-open browser after a short delay (non-blocking)
(sleep 2 && xdg-open "http://localhost:7860" 2>/dev/null || true) &

docker compose up web
