#!/usr/bin/env bash
# Dashboard watchdog wrapper — prefer: applypilot serve-daemon start
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run python -m applypilot.server.runtime "${1:-start}"
