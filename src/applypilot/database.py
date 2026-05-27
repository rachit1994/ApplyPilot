"""ApplyPilot database layer: schema, migrations, stats, and connection helpers.

Single source of truth for the jobs table schema. All columns from every
pipeline stage are created up front so any stage can run independently
without migration ordering issues.
"""

import json
import sqlite3
import threading
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
    # Scoring
    "fit_score": "INTEGER",
    "score_reasoning": "TEXT",
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


def get_stats(conn: sqlite3.Connection | None = None) -> dict:
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
    if conn is None:
        conn = get_connection()

    stats: dict = {}

    # Total jobs
    stats["total"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    # By site breakdown
    rows = conn.execute(
        "SELECT site, COUNT(*) as cnt FROM jobs GROUP BY site ORDER BY cnt DESC"
    ).fetchall()
    stats["by_site"] = [(row[0], row[1]) for row in rows]

    # Enrichment stage
    stats["pending_detail"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL"
    ).fetchone()[0]

    stats["with_description"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL"
    ).fetchone()[0]

    stats["detail_errors"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE detail_error IS NOT NULL"
    ).fetchone()[0]

    # Scoring stage
    stats["scored"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL"
    ).fetchone()[0]

    stats["unscored"] = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE full_description IS NOT NULL AND fit_score IS NULL"
    ).fetchone()[0]

    # Score distribution
    dist_rows = conn.execute(
        "SELECT fit_score, COUNT(*) as cnt FROM jobs "
        "WHERE fit_score IS NOT NULL "
        "GROUP BY fit_score ORDER BY fit_score DESC"
    ).fetchall()
    stats["score_distribution"] = [(row[0], row[1]) for row in dist_rows]

    # Tailoring stage
    stats["tailored"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL"
    ).fetchone()[0]

    stats["untailored_eligible"] = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE fit_score >= 7 AND full_description IS NOT NULL "
        "AND tailored_resume_path IS NULL"
    ).fetchone()[0]

    stats["tailor_exhausted"] = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE COALESCE(tailor_attempts, 0) >= 5 "
        "AND tailored_resume_path IS NULL"
    ).fetchone()[0]

    # Cover letter stage
    stats["with_cover_letter"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE cover_letter_path IS NOT NULL"
    ).fetchone()[0]

    stats["cover_exhausted"] = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE COALESCE(cover_attempts, 0) >= 5 "
        "AND (cover_letter_path IS NULL OR cover_letter_path = '')"
    ).fetchone()[0]

    # Application stage
    stats["applied"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE apply_status = 'applied'"
    ).fetchone()[0]

    stats["submitted_unverified"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE apply_status = 'submitted_unverified'"
    ).fetchone()[0]

    stats["apply_errors"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE apply_error IS NOT NULL"
    ).fetchone()[0]

    max_apply_attempts = config.DEFAULTS["max_apply_attempts"]
    stats["ready_to_apply"] = conn.execute(
        "SELECT COUNT(*) FROM jobs "
        "WHERE tailored_resume_path IS NOT NULL "
        "AND applied_at IS NULL "
        "AND (apply_status IS NULL OR apply_status = 'failed') "
        "AND (apply_attempts IS NULL OR apply_attempts < ?)",
        (max_apply_attempts,),
    ).fetchone()[0]

    stats["apply_manual"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE apply_status = 'manual'"
    ).fetchone()[0]

    # Referral outreach funnel
    stats["referral_recruiter_scraped"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE recruiter_public_id IS NOT NULL"
    ).fetchone()[0]
    stats["referral_pending_connect"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE referral_status = 'pending_connect'"
    ).fetchone()[0]
    stats["referral_connect_sent"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE referral_status = 'connect_sent'"
    ).fetchone()[0]
    stats["referral_message_sent"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE referral_status = 'message_sent'"
    ).fetchone()[0]
    stats["referral_failed"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE referral_status = 'failed'"
    ).fetchone()[0]
    stats["referral_skipped"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE referral_status = 'skipped'"
    ).fetchone()[0]
    stats["referral_connects_this_week"] = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE referral_connect_at >= datetime('now', '-7 days')
          AND referral_connect_at IS NOT NULL
        """
    ).fetchone()[0]

    return stats


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
            existing += 1
            continue

        try:
            conn.execute(
                "INSERT INTO jobs (url, title, salary, description, location, site, "
                "content_hash, sources, strategy, discovered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, job.get("title"), job.get("salary"), job.get("description"),
                 job.get("location"), site, content_hash, site, strategy, now),
            )
            new += 1
        except sqlite3.IntegrityError:
            _append_job_source(conn, url, site)
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


def refresh_source_stats_scores(conn: sqlite3.Connection | None = None, *, run_id: str = "") -> None:
    """Refresh per-source score counts for source telemetry rows."""
    if conn is None:
        conn = get_connection()
    ensure_source_stats_table(conn)
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
              AND LOWER(COALESCE(site, '')) = LOWER(discover_source_stats.source)
        )
        {where}
        """,
        params,
    )
    conn.commit()


def refresh_source_stats_tailored(conn: sqlite3.Connection | None = None, *, run_id: str = "") -> None:
    """Refresh per-source tailored counts for source telemetry rows."""
    if conn is None:
        conn = get_connection()
    ensure_source_stats_table(conn)
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
              AND LOWER(COALESCE(site, '')) = LOWER(discover_source_stats.source)
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
        ORDER BY
            CASE WHEN SUM(discovered) > 0
                THEN CAST(SUM(scored_ge7) AS REAL) / SUM(discovered)
                ELSE 0
            END DESC,
            SUM(scored_ge7) DESC,
            SUM(discovered) DESC
        """,
        (f"-{max(1, int(days))} days",),
    ).fetchall()
    return [
        {
            "source": row["source"],
            "discovered": int(row["discovered"] or 0),
            "passed_filter": int(row["passed_filter"] or 0),
            "scored_ge7": int(row["scored_ge7"] or 0),
            "tailored": int(row["tailored"] or 0),
            "efficiency": (
                float(row["scored_ge7"] or 0) / float(row["discovered"])
                if row["discovered"]
                else 0.0
            ),
        }
        for row in rows
    ]


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
        "pending_detail": "detail_scraped_at IS NULL",
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
    params: list = []

    if "?" in where and min_score is not None:
        params.append(min_score)
    elif "?" in where:
        params.append(7)  # default min_score

    if min_score is not None and "fit_score" not in where and stage in ("scored", "tailored", "applied"):
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
