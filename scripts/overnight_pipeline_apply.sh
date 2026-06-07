#!/usr/bin/env bash
# Full pipeline + autonomous apply (no login waits, no Claude escalation).
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
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/overnight-${STAMP}.log"
exec >>"$LOG" 2>&1

DB="$HOME/.applypilot/applypilot.db"

snapshot() {
  local label="$1"
  echo ""
  echo "=== $label $(date -Iseconds) ==="
  uv run python - <<'PY'
from applypilot.apply.launcher import count_acquirable_jobs

for ms in (7, 5):
    n = count_acquirable_jobs(min_score=ms, include_untailored=True)
    print(f"acquirable min_score={ms}: {n}")
PY
  sqlite3 "$DB" "
    SELECT 'applied_total', COUNT(*) FROM jobs
      WHERE applied_at IS NOT NULL OR apply_status IN ('applied','submitted');
    SELECT 'applied_tonight', COUNT(*) FROM jobs
      WHERE applied_at IS NOT NULL
        AND datetime(applied_at) >= datetime('now', 'start of day');
    SELECT apply_status, COUNT(*) FROM jobs
      WHERE fit_score >= 7 AND applied_at IS NULL
      GROUP BY apply_status ORDER BY 2 DESC;
  "
}

echo "Overnight run started $(date -Iseconds)"
echo "Log: $LOG"
snapshot "BEFORE"

echo ""
echo ">>> Pipeline: enrich filter score tailor pdf (skip discover — queue already loaded)"
if ! uv run applypilot run enrich filter score tailor pdf \
  --min-score 7 --validation lenient; then
  echo "WARNING: pipeline stage failed — continuing to apply anyway"
fi

snapshot "AFTER PIPELINE"

echo ""
echo ">>> Apply: deterministic-only, continuous, min-score 7, no human login wait"
uv run applypilot apply \
  --plain \
  --continuous \
  --deterministic-only \
  --include-untailored \
  --min-score 7 \
  --min-experience-years 5

snapshot "AFTER APPLY"
echo ""
echo "Overnight run finished $(date -Iseconds)"
