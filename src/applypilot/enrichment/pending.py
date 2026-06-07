"""Enrich queue rules: which jobs need detail scraping and how failures are retried."""

from __future__ import annotations

from datetime import datetime, timezone

from applypilot.db.connection import Connection
from applypilot.db.dialect import scalar

# Per-run Playwright goto retries inside scrape_detail_page.
DETAIL_GOTO_ATTEMPTS = 3

# Max pipeline passes after a retryable failure before the job is skipped.
MAX_DETAIL_ENRICH_ATTEMPTS = 3

_RETRYABLE_DETAIL_ERRORS: frozenset[str] = frozenset(
    {
        "timeout",
        "HTTP 408",
        "HTTP 429",
        "HTTP 500",
        "HTTP 502",
        "HTTP 503",
        "HTTP 504",
    }
)


def is_retryable_detail_error(error: str | None) -> bool:
    if not error:
        return False
    return error.strip() in _RETRYABLE_DETAIL_ERRORS


def detail_pending_clause() -> str:
    """SQL boolean for jobs that still need enrich (never scraped or retryable failure)."""
    retry_in = ", ".join(f"'{e}'" for e in sorted(_RETRYABLE_DETAIL_ERRORS))
    return f"""(
        detail_scraped_at IS NULL
        OR (
            (full_description IS NULL OR TRIM(COALESCE(full_description, '')) = '')
            AND detail_error IN ({retry_in})
            AND COALESCE(detail_enrich_attempts, 0) < {MAX_DETAIL_ENRICH_ATTEMPTS}
        )
    )"""


def count_pending_detail(conn: Connection) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM jobs WHERE {detail_pending_clause()}"
    ).fetchone()
    return int(scalar(row) or 0)


def persist_detail_scrape_result(
    conn: Connection,
    url: str,
    result: dict,
    *,
    now: str | None = None,
) -> None:
    """Write enrich outcome; retryable errors leave the job on the pending queue."""
    if now is None:
        now = datetime.now(timezone.utc).isoformat()

    status = result.get("status")
    err = result.get("error")

    if status in ("ok", "partial"):
        conn.execute(
            """
            UPDATE jobs
            SET full_description = ?,
                application_url = ?,
                detail_scraped_at = ?,
                detail_error = NULL
            WHERE url = ?
            """,
            (
                result.get("full_description"),
                result.get("application_url"),
                now,
                url,
            ),
        )
        return

    error_text = err or "unknown"
    row = conn.execute(
        "SELECT COALESCE(detail_enrich_attempts, 0) AS detail_enrich_attempts FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    attempts = int(row["detail_enrich_attempts"] or 0) + 1 if row else 1

    if is_retryable_detail_error(error_text) and attempts < MAX_DETAIL_ENRICH_ATTEMPTS:
        conn.execute(
            """
            UPDATE jobs
            SET detail_error = ?,
                detail_scraped_at = NULL,
                detail_enrich_attempts = ?
            WHERE url = ?
            """,
            (error_text, attempts, url),
        )
        return

    conn.execute(
        """
        UPDATE jobs
        SET detail_error = ?,
            detail_scraped_at = ?,
            detail_enrich_attempts = ?
        WHERE url = ?
        """,
        (error_text, now, attempts, url),
    )
