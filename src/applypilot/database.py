"""ApplyPilot database layer: schema, migrations, stats, and connection helpers.

Single source of truth for the jobs table schema. All columns from every
pipeline stage are created up front so any stage can run independently
without migration ordering issues.
"""

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path

from applypilot import config
from applypilot.config import DB_PATH

# Thread-local connection storage — each thread gets its own connection
# (required for SQLite thread safety with parallel workers)
_local = threading.local()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a thread-local cached SQLite connection with WAL mode enabled.

    Each thread gets its own connection (required for SQLite thread safety).
    Connections are cached and reused within the same thread.

    Args:
        db_path: Override the default DB_PATH. Useful for testing.

    Returns:
        sqlite3.Connection configured with WAL mode and row factory.
    """
    path = str(db_path or DB_PATH)

    if not hasattr(_local, 'connections'):
        _local.connections = {}

    conn = _local.connections.get(path)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass

    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    _local.connections[path] = conn
    return conn


def close_connection(db_path: Path | str | None = None) -> None:
    """Close the cached connection for the current thread."""
    path = str(db_path or DB_PATH)
    if hasattr(_local, 'connections'):
        conn = _local.connections.pop(path, None)
        if conn is not None:
            conn.close()


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create the full jobs table with all columns from every pipeline stage.

    This is idempotent -- safe to call on every startup. Uses CREATE TABLE IF NOT EXISTS
    so it won't destroy existing data.

    Schema columns by stage:
      - Discovery:  url, title, salary, description, location, site, strategy, discovered_at
      - Enrichment: full_description, application_url, detail_scraped_at, detail_error
      - Scoring:    fit_score, score_reasoning, scored_at
      - Tailoring:  tailored_resume_path, tailored_at, tailor_attempts
      - Cover:      cover_letter_path, cover_letter_at, cover_attempts
      - Apply:      applied_at, apply_status, apply_error, apply_attempts,
                   agent_id, last_attempted_at, apply_duration_ms, apply_task_id,
                   verification_confidence

    Apply statuses are free-form text for forward compatibility. Known values:
    in_progress, applied, submitted_unverified, failed, manual, expired,
    captcha, login_issue, already_applied, account_required.

    Args:
        db_path: Override the default DB_PATH.

    Returns:
        sqlite3.Connection with the schema initialized.
    """
    path = db_path or DB_PATH

    # Ensure parent directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            -- Discovery stage (smart_extract / job_search)
            url                   TEXT PRIMARY KEY,
            title                 TEXT,
            salary                TEXT,
            description           TEXT,
            location              TEXT,
            site                  TEXT,
            content_hash          TEXT,
            sources               TEXT,
            strategy              TEXT,
            discovered_at         TEXT,

            -- Enrichment stage (detail_scraper)
            full_description      TEXT,
            application_url       TEXT,
            detail_scraped_at     TEXT,
            detail_error          TEXT,

            -- Scoring stage (job_scorer)
            pre_fit_score        INTEGER,
            pre_filter_reason    TEXT,
            pre_filter_rejected_at TEXT,
            fit_score             INTEGER,
            score_reasoning       TEXT,
            scored_at             TEXT,

            -- Tailoring stage (resume tailor)
            tailored_resume_path  TEXT,
            tailored_at           TEXT,
            tailor_attempts       INTEGER DEFAULT 0,

            -- Cover letter stage
            cover_letter_path     TEXT,
            cover_letter_at       TEXT,
            cover_attempts        INTEGER DEFAULT 0,

            -- Application stage
            applied_at            TEXT,
            apply_status          TEXT,
            apply_error           TEXT,
            apply_attempts        INTEGER DEFAULT 0,
            agent_id              TEXT,
            last_attempted_at     TEXT,
            apply_duration_ms     INTEGER,
            apply_task_id         TEXT,
            verification_confidence TEXT
        )
    """)
    ensure_source_stats_table(conn)
    ensure_llm_usage_table(conn)
    ensure_dashboard_activity_table(conn)
    ensure_qa_bank_table(conn)
    ensure_apply_outcomes_table(conn)
    ensure_field_overrides_table(conn)
    conn.commit()

    # Run migrations for any columns added after initial schema
    ensure_columns(conn)

    from applypilot.inbox.db import init_inbox_schema
    from applypilot.orchestration.events import init_run_schema

    init_inbox_schema(conn)
    init_run_schema(conn)

    return conn


def ensure_source_stats_table(conn: sqlite3.Connection | None = None) -> None:
    """Create discover source telemetry table."""
    if conn is None:
        conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discover_source_stats (
            source TEXT NOT NULL,
            run_id TEXT NOT NULL,
            discovered INTEGER DEFAULT 0,
            passed_filter INTEGER DEFAULT 0,
            scored_ge7 INTEGER DEFAULT 0,
            tailored INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )


def ensure_llm_usage_table(conn: sqlite3.Connection | None = None) -> None:
    """Create a durable LLM usage/cost ledger."""
    if conn is None:
        conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            operation TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            estimated INTEGER DEFAULT 1,
            cost_usd REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            metadata_json TEXT
        )
        """
    )


def ensure_dashboard_activity_table(conn: sqlite3.Connection | None = None) -> None:
    """Persist dashboard-wide activity rows for /api/activity and SSE."""
    if conn is None:
        conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            stage TEXT,
            message TEXT NOT NULL,
            run_id TEXT,
            job_url TEXT,
            meta_json TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dashboard_activity_id "
        "ON dashboard_activity_events(id)"
    )


def ensure_qa_bank_table(conn: sqlite3.Connection | None = None) -> None:
    """Create the Resolver Tier-1 Q&A answer cache.

    A normalized question key maps to a stored answer so the deterministic
    apply Driver can fill standard screening fields without an LLM call.

    Key design (see docs/maxed-apply-pipeline-jun-2026.md §5 and
    docs/direct-apply-architecture.md §7): the question_key folds in the
    section header and the input name/autocomplete attribute so that an
    ambiguous label ("Email" under "Referrer" vs "Personal", "Name" =
    full vs company vs referrer) cannot leak a wrong cached answer.

        question_key = sha1(
            norm(label) | norm(section_header) | norm(name_attr) | answer_type
        )

    answer_type semantics:
      - text / select / bool / number -> answer is served verbatim from cache.
      - template -> answer holds a Gemini prompt template; the Resolver
        re-renders it at fill time with live {company, role, jd} context and
        never serves cached prose (anti-boilerplate).
    """
    if conn is None:
        conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_bank (
            question_key   TEXT PRIMARY KEY,
            question_text  TEXT,
            answer         TEXT,
            answer_type    TEXT,
            section_header TEXT,
            name_attr      TEXT,
            scope          TEXT DEFAULT 'generic',
            source         TEXT DEFAULT 'gemini',
            hit_count      INTEGER DEFAULT 0,
            created_at     TEXT,
            updated_at     TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qa_bank_hit_count "
        "ON qa_bank(hit_count)"
    )


def ensure_apply_outcomes_table(conn: sqlite3.Connection | None = None) -> None:
    """Create the per-apply observability/training-signal ledger.

    One row per Driver apply attempt. Powers the success-metric dashboard
    (applies/day, escalation rate, per-ATS-family throughput) today and the
    v2 declarative learning loop (docs/direct-apply-architecture.md §10) later.

        url            -- job URL (FK to jobs.url, not enforced)
        ats_family     -- greenhouse | lever | ashby | workday | ... | unknown
        fingerprint    -- ats_family + DOM signature (provider identity)
        result         -- final Driver result string (applied, failed:*, ...)
        tier_resolved  -- highest Resolver tier used: 0 | 1 | 2 | 3(escalated)
        escalated      -- 1 if handed to Claude rescue
        escalate_reason-- §8 trigger that caused escalation (NULL if none)
        fields_total   -- fillable fields seen on the form
        fields_llm     -- fields that needed Tier-2 Gemini
        elapsed_ms     -- wall time for the attempt
        created_at     -- ISO8601 UTC
    """
    if conn is None:
        conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS apply_outcomes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT NOT NULL,
            ats_family      TEXT,
            fingerprint     TEXT,
            result          TEXT,
            tier_resolved   INTEGER,
            escalated       INTEGER DEFAULT 0,
            escalate_reason TEXT,
            fields_total    INTEGER DEFAULT 0,
            fields_llm      INTEGER DEFAULT 0,
            elapsed_ms      INTEGER,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apply_outcomes_created "
        "ON apply_outcomes(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apply_outcomes_fingerprint "
        "ON apply_outcomes(fingerprint)"
    )


def record_apply_outcome(
    conn: sqlite3.Connection | None = None,
    *,
    url: str,
    ats_family: str | None = None,
    fingerprint: str | None = None,
    result: str | None = None,
    tier_resolved: int | None = None,
    escalated: bool = False,
    escalate_reason: str | None = None,
    fields_total: int = 0,
    fields_llm: int = 0,
    elapsed_ms: int | None = None,
    created_at: str | None = None,
) -> None:
    """Append one apply-outcome row (Driver observability + learner signal)."""
    if conn is None:
        conn = get_connection()
    ensure_apply_outcomes_table(conn)
    conn.execute(
        """
        INSERT INTO apply_outcomes (
            url, ats_family, fingerprint, result, tier_resolved,
            escalated, escalate_reason, fields_total, fields_llm,
            elapsed_ms, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            ats_family,
            fingerprint,
            result,
            tier_resolved,
            1 if escalated else 0,
            escalate_reason,
            max(0, int(fields_total or 0)),
            max(0, int(fields_llm or 0)),
            elapsed_ms,
            created_at or datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Field overrides — user corrections that win over rules/cache/LLM everywhere
# ---------------------------------------------------------------------------

def _override_key(label: str | None) -> str:
    """Normalize a field label to a stable, cross-company override key."""
    import re

    text = (label or "").strip().lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ensure_field_overrides_table(conn: sqlite3.Connection | None = None) -> None:
    """Create the user-correction store.

    One row per normalized field label. The Resolver consults this FIRST (ahead
    of profile rules, the Q&A cache, and Gemini), so a correction the user makes
    once is applied to that field on every future form, for any company. Keyed
    by the normalized label only (not name_attr) so it generalizes across ATSes.
    """
    if conn is None:
        conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS field_overrides (
            label_key  TEXT PRIMARY KEY,
            label      TEXT,
            value      TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )


def get_field_override(label: str | None, conn: sqlite3.Connection | None = None) -> str | None:
    """Return the user-corrected value for a field label, or None."""
    key = _override_key(label)
    if not key:
        return None
    if conn is None:
        conn = get_connection()
    ensure_field_overrides_table(conn)
    row = conn.execute(
        "SELECT value FROM field_overrides WHERE label_key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def set_field_override(
    label: str, value: str, conn: sqlite3.Connection | None = None
) -> str:
    """Upsert a user correction for a field label. Returns the label_key."""
    key = _override_key(label)
    if not key:
        raise ValueError("label is required for an override")
    if conn is None:
        conn = get_connection()
    ensure_field_overrides_table(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO field_overrides (label_key, label, value, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(label_key) DO UPDATE SET
            label = excluded.label,
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, label, value, now, now),
    )
    conn.commit()
    return key


def list_field_overrides(conn: sqlite3.Connection | None = None) -> list[dict]:
    if conn is None:
        conn = get_connection()
    ensure_field_overrides_table(conn)
    rows = conn.execute(
        "SELECT label, value, updated_at FROM field_overrides ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_field_override(label: str, conn: sqlite3.Connection | None = None) -> bool:
    key = _override_key(label)
    if conn is None:
        conn = get_connection()
    ensure_field_overrides_table(conn)
    cur = conn.execute("DELETE FROM field_overrides WHERE label_key = ?", (key,))
    conn.commit()
    return cur.rowcount > 0


def record_llm_usage(
    conn: sqlite3.Connection | None = None,
    *,
    provider: str,
    model: str,
    operation: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
    estimated: bool = True,
    cost_usd: float = 0.0,
    metadata: dict | None = None,
    created_at: str | None = None,
) -> None:
    """Append one LLM usage event for monthly billing analysis."""
    if conn is None:
        conn = get_connection()
    ensure_llm_usage_table(conn)
    conn.execute(
        """
        INSERT INTO llm_usage_events (
            provider, model, operation, input_tokens, output_tokens,
            cache_read_tokens, cache_create_tokens, estimated, cost_usd,
            created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider,
            model,
            operation,
            max(0, int(input_tokens or 0)),
            max(0, int(output_tokens or 0)),
            max(0, int(cache_read_tokens or 0)),
            max(0, int(cache_create_tokens or 0)),
            1 if estimated else 0,
            max(0.0, float(cost_usd or 0.0)),
            created_at or datetime.now(timezone.utc).isoformat(),
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    conn.commit()


def get_llm_usage_monthly(
    conn: sqlite3.Connection | None = None,
    *,
    month: str | None = None,
) -> list[dict]:
    """Return usage grouped by provider/model/operation for YYYY-MM."""
    if conn is None:
        conn = get_connection()
    ensure_llm_usage_table(conn)
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = conn.execute(
        """
        SELECT
            provider,
            model,
            operation,
            COUNT(*) AS calls,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_create_tokens) AS cache_create_tokens,
            SUM(cost_usd) AS cost_usd,
            SUM(CASE WHEN estimated THEN 1 ELSE 0 END) AS estimated_calls
        FROM llm_usage_events
        WHERE substr(created_at, 1, 7) = ?
        GROUP BY provider, model, operation
        ORDER BY cost_usd DESC, calls DESC
        """,
        (month,),
    ).fetchall()
    return [
        {
            "provider": row["provider"],
            "model": row["model"],
            "operation": row["operation"],
            "calls": int(row["calls"] or 0),
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "cache_read_tokens": int(row["cache_read_tokens"] or 0),
            "cache_create_tokens": int(row["cache_create_tokens"] or 0),
            "cost_usd": float(row["cost_usd"] or 0.0),
            "estimated_calls": int(row["estimated_calls"] or 0),
        }
        for row in rows
    ]


# Complete column registry: column_name -> SQL type with optional default.
# This is the single source of truth. Adding a column here is all that's needed
# for it to appear in both new databases and migrated ones.
_ALL_COLUMNS: dict[str, str] = {
    # Discovery
    "url": "TEXT PRIMARY KEY",
    "title": "TEXT",
    "salary": "TEXT",
    "description": "TEXT",
    "location": "TEXT",
    "site": "TEXT",
    "content_hash": "TEXT",
    "sources": "TEXT",
    "strategy": "TEXT",
    "discovered_at": "TEXT",
    # Enrichment
    "full_description": "TEXT",
    "application_url": "TEXT",
    "detail_scraped_at": "TEXT",
    "detail_error": "TEXT",
    "detail_enrich_attempts": "INTEGER DEFAULT 0",
    # Scoring
    "pre_fit_score": "INTEGER",
    "pre_filter_reason": "TEXT",
    "pre_filter_rejected_at": "TEXT",
    "fit_score": "INTEGER",
    "score_reasoning": "TEXT",
    "score_role_key": "TEXT",
    "score_jd_fit": "INTEGER",
    "scored_at": "TEXT",
    # Tailoring
    "tailored_resume_path": "TEXT",
    "tailored_at": "TEXT",
    "tailor_attempts": "INTEGER DEFAULT 0",
    # Cover letter
    "cover_letter_path": "TEXT",
    "cover_letter_at": "TEXT",
    "cover_attempts": "INTEGER DEFAULT 0",
    # Application
    "applied_at": "TEXT",
    "apply_status": "TEXT",
    "apply_error": "TEXT",
    "apply_attempts": "INTEGER DEFAULT 0",
    # Apply retry/backoff (do not attempt before this time, ISO8601)
    "apply_not_before": "TEXT",
    "agent_id": "TEXT",
    "last_attempted_at": "TEXT",
    "apply_duration_ms": "INTEGER",
    "apply_task_id": "TEXT",
    "verification_confidence": "TEXT",
    "apply_log_path": "TEXT",
    "apply_form_filled": "TEXT",
    # Referral outreach (OpenOutreach)
    "recruiter_public_id": "TEXT",
    "recruiter_name": "TEXT",
    "recruiter_linkedin_url": "TEXT",
    "recruiter_scraped_at": "TEXT",
    "recruiter_scrape_error": "TEXT",
    "referral_message": "TEXT",
    "referral_status": "TEXT",
    "referral_connect_at": "TEXT",
    "referral_message_at": "TEXT",
    "referral_error": "TEXT",
    "referral_openoutreach_deal_id": "TEXT",
    "referral_resume_path": "TEXT",
    # Recruiter reply instrumentation (WP-1; read-only inbox classification)
    "reply_status": "TEXT",
    "reply_at": "TEXT",
    "reply_channel": "TEXT",
    "reply_source_id": "TEXT",
}


def ensure_columns(conn: sqlite3.Connection | None = None) -> list[str]:
    """Add any missing columns to the jobs table (forward migration).

    Reads the current table schema via PRAGMA table_info and compares against
    the full column registry. Any missing columns are added with ALTER TABLE.

    This makes it safe to upgrade the database from any previous version --
    columns are only added, never removed or renamed.

    Args:
        conn: Database connection. Uses get_connection() if None.

    Returns:
        List of column names that were added (empty if schema was already current).
    """
    if conn is None:
        conn = get_connection()

    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    added = []

    for col, dtype in _ALL_COLUMNS.items():
        if col not in existing:
            # PRIMARY KEY columns can't be added via ALTER TABLE, but url
            # is always created with the table itself so this is safe
            if "PRIMARY KEY" in dtype:
                continue
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {dtype}")
            added.append(col)

    if added:
        conn.commit()

    return added


_STATS_CACHE_TTL_S = 2.0
_stats_cache: tuple[float, dict] | None = None
_stats_cache_lock = threading.Lock()


def invalidate_stats_cache() -> None:
    """Drop cached dashboard stats (e.g. after bulk DB writes)."""
    global _stats_cache
    with _stats_cache_lock:
        _stats_cache = None
    try:
        from applypilot.role_resumes import invalidate_tailor_count_cache

        invalidate_tailor_count_cache()
    except Exception:
        pass


def get_stats(conn: sqlite3.Connection | None = None, *, use_cache: bool = True) -> dict:
    """Return job counts by pipeline stage.

    Provides a snapshot of how many jobs are at each stage, useful for
    dashboard display and pipeline progress tracking.

    Args:
        conn: Database connection. Uses get_connection() if None.

    Returns:
        Dictionary with keys:
            total, by_site, pending_detail, with_description,
            scored, unscored, tailored, untailored_eligible,
            with_cover_letter, applied, score_distribution
    """
    global _stats_cache
    if conn is not None:
        use_cache = False
    if use_cache:
        now = time.monotonic()
        with _stats_cache_lock:
            if _stats_cache is not None:
                cached_at, cached = _stats_cache
                if now - cached_at < _STATS_CACHE_TTL_S:
                    return dict(cached)

    stats = _compute_job_stats(conn)

    if use_cache:
        with _stats_cache_lock:
            _stats_cache = (time.monotonic(), stats)

    return stats


def _compute_job_stats(conn: sqlite3.Connection | None = None) -> dict:
    """Uncached job counts for dashboard and pipeline progress."""
    if conn is None:
        conn = get_connection()

    from applypilot.enrichment.pending import detail_pending_clause

    pending_detail_sql = detail_pending_clause()
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN {pending_detail_sql} THEN 1 ELSE 0 END) AS pending_detail,
          SUM(CASE WHEN full_description IS NOT NULL THEN 1 ELSE 0 END) AS with_description,
          SUM(CASE WHEN detail_error IS NOT NULL THEN 1 ELSE 0 END) AS detail_errors,
          SUM(CASE WHEN pre_filter_rejected_at IS NOT NULL THEN 1 ELSE 0 END) AS pre_filter_rejected,
          SUM(CASE WHEN pre_fit_score IS NOT NULL
                    AND pre_filter_rejected_at IS NULL
                    AND pre_filter_reason IS NULL THEN 1 ELSE 0 END) AS pre_filter_kept,
          SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
          SUM(CASE WHEN full_description IS NOT NULL AND fit_score IS NULL THEN 1 ELSE 0 END) AS unscored,
          SUM(CASE WHEN tailored_resume_path IS NOT NULL THEN 1 ELSE 0 END) AS tailored,
          SUM(CASE WHEN COALESCE(tailor_attempts, 0) >= 5
                    AND tailored_resume_path IS NULL THEN 1 ELSE 0 END) AS tailor_exhausted,
          SUM(CASE WHEN cover_letter_path IS NOT NULL THEN 1 ELSE 0 END) AS with_cover_letter,
          SUM(CASE WHEN COALESCE(cover_attempts, 0) >= 5
                    AND (cover_letter_path IS NULL OR cover_letter_path = '') THEN 1 ELSE 0 END) AS cover_exhausted,
          SUM(CASE WHEN apply_status = 'applied' THEN 1 ELSE 0 END) AS applied,
          SUM(CASE WHEN apply_status = 'submitted_unverified' THEN 1 ELSE 0 END) AS submitted_unverified,
          SUM(CASE WHEN apply_error IS NOT NULL THEN 1 ELSE 0 END) AS apply_errors,
          SUM(CASE WHEN apply_status = 'manual' THEN 1 ELSE 0 END) AS apply_manual,
          SUM(CASE WHEN recruiter_public_id IS NOT NULL THEN 1 ELSE 0 END) AS referral_recruiter_scraped,
          SUM(CASE WHEN referral_status = 'pending_connect' THEN 1 ELSE 0 END) AS referral_pending_connect,
          SUM(CASE WHEN referral_status = 'connect_sent' THEN 1 ELSE 0 END) AS referral_connect_sent,
          SUM(CASE WHEN referral_status = 'message_sent' THEN 1 ELSE 0 END) AS referral_message_sent,
          SUM(CASE WHEN referral_status = 'failed' THEN 1 ELSE 0 END) AS referral_failed,
          SUM(CASE WHEN referral_status = 'skipped' THEN 1 ELSE 0 END) AS referral_skipped,
          SUM(CASE WHEN referral_connect_at IS NOT NULL
                    AND referral_connect_at >= datetime('now', '-7 days') THEN 1 ELSE 0 END) AS referral_connects_this_week
        FROM jobs
        """
    ).fetchone()

    stats: dict = {key: int(row[key] or 0) for key in row.keys()}

    site_rows = conn.execute(
        "SELECT site, COUNT(*) as cnt FROM jobs GROUP BY site ORDER BY cnt DESC"
    ).fetchall()
    stats["by_site"] = [(site_row[0], site_row[1]) for site_row in site_rows]

    dist_rows = conn.execute(
        "SELECT fit_score, COUNT(*) as cnt FROM jobs "
        "WHERE fit_score IS NOT NULL "
        "GROUP BY fit_score ORDER BY fit_score DESC"
    ).fetchall()
    stats["score_distribution"] = [(dist_row[0], dist_row[1]) for dist_row in dist_rows]

    from applypilot.role_resumes import count_jobs_needing_tailor

    stats["untailored_eligible"] = count_jobs_needing_tailor(conn, min_score=7)
    stats["apply_queue_min_ready"] = int(config.DEFAULTS.get("apply_queue_min_ready", 300))

    from applypilot.apply.launcher import count_acquirable_jobs

    stats["ready_to_apply"] = count_acquirable_jobs()
    stats["claude_escalated"] = count_claude_escalated_jobs(conn)

    return stats


def count_claude_escalated_jobs(conn: sqlite3.Connection | None = None) -> int:
    """Jobs in the apply ledger deferred to or handled by Claude rescue."""
    if conn is None:
        conn = get_connection()
    ensure_apply_outcomes_table(conn)
    row = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE (
            COALESCE(apply_error, '') LIKE 'pending_claude_rescue%'
            OR url IN (SELECT DISTINCT url FROM apply_outcomes WHERE escalated = 1)
        )
        AND (
            apply_status IN ('applied', 'submitted_unverified', 'failed', 'manual')
            OR applied_at IS NOT NULL
        )
        """
    ).fetchone()
    return int(row[0] or 0)


def _content_hash_for_job(job: dict, site: str = "") -> str:
    """Return the cross-source content fingerprint for a discovered job."""
    title = str(job.get("title") or "").strip().lower()
    location = str(job.get("location") or "").strip().lower()
    company = str(job.get("company") or job.get("company_name") or site or "").strip().lower()
    return md5(f"{title}|{company}|{location}".encode("utf-8")).hexdigest()


def _append_job_source(conn: sqlite3.Connection, url: str, site: str) -> None:
    row = conn.execute(
        "SELECT site, sources FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    if row is None:
        return

    existing_site = row["site"] if isinstance(row, sqlite3.Row) else row[0]
    existing_sources = row["sources"] if isinstance(row, sqlite3.Row) else row[1]
    parts = []
    for value in (existing_sources, existing_site, site):
        for part in str(value or "").split(","):
            part = part.strip()
            if part and part not in parts:
                parts.append(part)

    conn.execute(
        "UPDATE jobs SET sources = ? WHERE url = ?",
        (",".join(parts) if parts else None, url),
    )


def store_jobs(conn: sqlite3.Connection, jobs: list[dict],
               site: str, strategy: str) -> tuple[int, int]:
    """Store discovered jobs, skipping duplicates by content hash before URL.

    Args:
        conn: Database connection.
        jobs: List of job dicts with keys: url, title, salary, description, location.
        site: Source site name (e.g. "RemoteOK", "Dice").
        strategy: Extraction strategy used (e.g. "json_ld", "api_response", "css_selectors").

    Returns:
        Tuple of (new_count, duplicate_count).
    """
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0

    from applypilot.discovery._filters import discover_job_passes

    ensure_columns(conn)

    def _backfill_detail_columns(existing_url: str, job: dict) -> None:
        application_url = job.get("application_url")
        full_description = job.get("full_description")
        if not application_url and not full_description:
            return
        conn.execute(
            """
            UPDATE jobs
            SET application_url = COALESCE(NULLIF(application_url, ''), ?),
                full_description = COALESCE(NULLIF(full_description, ''), ?),
                detail_scraped_at = CASE
                    WHEN (detail_scraped_at IS NULL OR detail_scraped_at = '')
                         AND ? IS NOT NULL
                    THEN ?
                    ELSE detail_scraped_at
                END
            WHERE url = ?
            """,
            (
                application_url,
                full_description,
                full_description,
                now,
                existing_url,
            ),
        )

    for job in jobs:
        url = job.get("url")
        if not url:
            continue
        if not discover_job_passes(job):
            continue
        content_hash = _content_hash_for_job(job, site)

        duplicate = conn.execute(
            "SELECT url FROM jobs WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        ).fetchone()
        if duplicate is not None:
            duplicate_url = (
                duplicate["url"] if isinstance(duplicate, sqlite3.Row) else duplicate[0]
            )
            _append_job_source(conn, duplicate_url, site)
            _backfill_detail_columns(duplicate_url, job)
            existing += 1
            continue

        application_url = job.get("application_url")
        full_description = job.get("full_description")
        detail_scraped_at = now if full_description else None
        try:
            conn.execute(
                "INSERT INTO jobs (url, title, salary, description, location, site, "
                "content_hash, sources, strategy, discovered_at, application_url, "
                "full_description, detail_scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, job.get("title"), job.get("salary"), job.get("description"),
                 job.get("location"), site, content_hash, site, strategy, now,
                 application_url, full_description, detail_scraped_at),
            )
            new += 1
        except sqlite3.IntegrityError:
            _append_job_source(conn, url, site)
            _backfill_detail_columns(url, job)
            existing += 1

    conn.commit()
    return new, existing


def record_discover_source_stats(
    conn: sqlite3.Connection | None,
    *,
    source: str,
    run_id: str = "",
    discovered: int = 0,
    passed_filter: int = 0,
    created_at: str | None = None,
) -> None:
    """Insert one source-quality telemetry row for a discover source run."""
    if conn is None:
        conn = get_connection()
    ensure_source_stats_table(conn)
    conn.execute(
        """
        INSERT INTO discover_source_stats
            (source, run_id, discovered, passed_filter, scored_ge7, tailored, created_at)
        VALUES (?, ?, ?, ?, 0, 0, ?)
        """,
        (
            source,
            run_id,
            max(0, int(discovered or 0)),
            max(0, int(passed_filter or 0)),
            created_at or datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


_DISCOVER_SOURCE_KEY_SQL = """
    CASE
        WHEN LOWER(COALESCE(site, '')) LIKE 'greenhouse:%'
             OR LOWER(COALESCE(site, '')) = 'greenhouse' THEN 'greenhouse'
        WHEN LOWER(COALESCE(site, '')) LIKE 'lever:%'
             OR LOWER(COALESCE(site, '')) = 'lever' THEN 'lever'
        WHEN LOWER(COALESCE(site, '')) LIKE 'ashby:%'
             OR LOWER(COALESCE(site, '')) = 'ashby' THEN 'ashby'
        ELSE NULL
    END
"""


def _live_scored_ge7_by_source(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
) -> dict[str, int]:
    """Count score≥7 jobs in the window, grouped by discover source key (site prefix)."""
    rows = conn.execute(
        f"""
        SELECT {_DISCOVER_SOURCE_KEY_SQL} AS source_key, COUNT(*) AS n
        FROM jobs
        WHERE fit_score >= 7
          AND discovered_at >= datetime('now', ?)
        GROUP BY source_key
        HAVING source_key IS NOT NULL
        """,
        (f"-{max(1, int(days))} days",),
    ).fetchall()
    return {str(row["source_key"]): int(row["n"] or 0) for row in rows}


def refresh_source_stats_scores(conn: sqlite3.Connection | None = None, *, run_id: str = "") -> None:
    """Refresh per-source score counts for source telemetry rows."""
    from applypilot.discovery.site_priority import sql_site_matches_discover_source

    if conn is None:
        conn = get_connection()
    ensure_source_stats_table(conn)
    site_match = sql_site_matches_discover_source("site", "discover_source_stats.source")
    if run_id:
        where = "WHERE run_id = ?"
        params: tuple[str, ...] = (run_id,)
    else:
        where = "WHERE run_id = ''"
        params = ()
    conn.execute(
        f"""
        UPDATE discover_source_stats
        SET scored_ge7 = (
            SELECT COUNT(*)
            FROM jobs
            WHERE fit_score >= 7
              AND scored_at >= discover_source_stats.created_at
              AND {site_match}
        )
        {where}
        """,
        params,
    )
    conn.commit()


def refresh_source_stats_tailored(conn: sqlite3.Connection | None = None, *, run_id: str = "") -> None:
    """Refresh per-source tailored counts for source telemetry rows."""
    from applypilot.discovery.site_priority import sql_site_matches_discover_source

    if conn is None:
        conn = get_connection()
    ensure_source_stats_table(conn)
    site_match = sql_site_matches_discover_source("site", "discover_source_stats.source")
    if run_id:
        where = "WHERE run_id = ?"
        params: tuple[str, ...] = (run_id,)
    else:
        where = "WHERE run_id = ''"
        params = ()
    conn.execute(
        f"""
        UPDATE discover_source_stats
        SET tailored = (
            SELECT COUNT(*)
            FROM jobs
            WHERE tailored_at >= discover_source_stats.created_at
              AND {site_match}
        )
        {where}
        """,
        params,
    )
    conn.commit()


def get_source_stats_rollup(
    conn: sqlite3.Connection | None = None,
    *,
    days: int = 7,
) -> list[dict]:
    """Return last-N-day source quality rollup sorted by high-score efficiency."""
    if conn is None:
        conn = get_connection()
    ensure_source_stats_table(conn)
    window = f"-{max(1, int(days))} days"
    rows = conn.execute(
        """
        SELECT
            source,
            SUM(discovered) AS discovered,
            SUM(passed_filter) AS passed_filter,
            SUM(scored_ge7) AS scored_ge7,
            SUM(tailored) AS tailored
        FROM discover_source_stats
        WHERE created_at >= datetime('now', ?)
        GROUP BY source
        ORDER BY SUM(discovered) DESC
        """,
        (window,),
    ).fetchall()
    live_scored = _live_scored_ge7_by_source(conn, days=days)
    out: list[dict] = []
    for row in rows:
        source = str(row["source"] or "")
        discovered = int(row["discovered"] or 0)
        scored_ge7 = live_scored.get(source.lower(), int(row["scored_ge7"] or 0))
        efficiency = float(scored_ge7) / float(discovered) if discovered else 0.0
        out.append(
            {
                "source": source,
                "discovered": discovered,
                "passed_filter": int(row["passed_filter"] or 0),
                "scored_ge7": scored_ge7,
                "tailored": int(row["tailored"] or 0),
                "efficiency": efficiency,
            }
        )
    out.sort(
        key=lambda r: (r["efficiency"], r["scored_ge7"], r["discovered"]),
        reverse=True,
    )
    return out


def get_jobs_by_stage(conn: sqlite3.Connection | None = None,
                      stage: str = "discovered",
                      min_score: int | None = None,
                      limit: int = 100) -> list[dict]:
    """Fetch jobs filtered by pipeline stage.

    Args:
        conn: Database connection. Uses get_connection() if None.
        stage: One of "discovered", "enriched", "scored", "tailored", "applied".
        min_score: Minimum fit_score filter (only relevant for scored+ stages).
        limit: Maximum number of rows to return.

    Returns:
        List of job dicts.
    """
    if conn is None:
        conn = get_connection()

    conditions = {
        "discovered": "1=1",
        "pending_detail": None,  # filled below with detail_pending_clause()
        "enriched": "full_description IS NOT NULL",
        "pending_score": "full_description IS NOT NULL AND fit_score IS NULL",
        "scored": "fit_score IS NOT NULL",
        "pending_tailor": (
            "fit_score >= ? AND full_description IS NOT NULL "
            "AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts, 0) < 5"
        ),
        "tailored": "tailored_resume_path IS NOT NULL",
        "pending_apply": (
            "tailored_resume_path IS NOT NULL AND applied_at IS NULL "
            "AND application_url IS NOT NULL"
        ),
        "applied": "apply_status = 'applied'",
    }

    where = conditions.get(stage, "1=1")
    if where is None and stage == "pending_detail":
        from applypilot.enrichment.pending import detail_pending_clause

        where = detail_pending_clause()
    params: list = []

    if where and "?" in where and min_score is not None:
        params.append(min_score)
    elif where and "?" in where:
        params.append(7)  # default min_score

    if (
        where
        and min_score is not None
        and "fit_score" not in where
        and stage in ("scored", "tailored", "applied")
    ):
        where += " AND fit_score >= ?"
        params.append(min_score)

    query = f"SELECT * FROM jobs WHERE {where} ORDER BY fit_score DESC NULLS LAST, discovered_at DESC"
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()

    # Convert sqlite3.Row objects to dicts
    if rows:
        columns = rows[0].keys()
        return [dict(zip(columns, row)) for row in rows]
    return []
