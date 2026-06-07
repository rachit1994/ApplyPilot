#!/usr/bin/env bash
# Autonomous apply loop — survives restarts, no login wait, no Claude escalation.
set -eo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$HOME/.applypilot/.env" ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$HOME/.applypilot/.env" | grep -v '^[[:space:]]*$' | xargs) || true
fi

export APPLYPILOT_APPLY_ENGINE=direct
export APPLYPILOT_DIRECT_ESCALATE=0
export APPLYPILOT_LOGIN_WAIT_SECONDS=0
export APPLYPILOT_DIRECT_JOB_TIMEOUT=600

LOG_DIR="$HOME/.applypilot/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/apply-overnight-$(date +%Y%m%d).log"
exec >>"$LOG" 2>&1

echo "=== apply daemon started $(date -Iseconds) ==="

while true; do
  echo "--- apply batch $(date -Iseconds) ---"
  if uv run applypilot apply \
    --plain \
    --continuous \
    --deterministic-only \
    --include-untailored \
    --min-score 7 \
    --min-experience-years 5 \
    --engine direct; then
    echo "apply exited cleanly $(date -Iseconds)"
    break
  fi
  echo "apply exited non-zero; restarting in 30s..."
  sleep 30
done

echo "=== apply daemon finished $(date -Iseconds) ==="
