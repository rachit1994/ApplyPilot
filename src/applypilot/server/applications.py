"""Applied jobs API queries."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from applypilot.apply.apply_log_parser import load_apply_log_detail
from applypilot.database import get_connection, init_db


def query_applied_jobs(
    *,
    limit: int = 100,
    offset: int = 0,
    include_failed: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    init_db()
    conn = get_connection()

    if include_failed:
        where = "WHERE apply_status IN ('applied', 'failed', 'manual') OR applied_at IS NOT NULL"
    else:
        where = "WHERE apply_status = 'applied'"

    total = conn.execute(f"SELECT COUNT(*) FROM jobs {where}").fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT url, title, site, location, salary, fit_score,
               application_url, apply_status, apply_error, applied_at,
               last_attempted_at, apply_duration_ms, apply_attempts,
               apply_log_path, verification_confidence
        FROM jobs
        {where}
        ORDER BY datetime(COALESCE(applied_at, last_attempted_at)) DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows], total


def get_application_detail(job_url: str) -> dict[str, Any] | None:
    init_db()
    conn = get_connection()
    url = unquote(job_url)
    row = conn.execute(
        """
        SELECT url, title, site, location, salary, fit_score, score_reasoning,
               application_url, apply_status, apply_error, applied_at,
               last_attempted_at, apply_duration_ms, apply_attempts,
               apply_log_path, verification_confidence, tailored_resume_path,
               cover_letter_path
        FROM jobs
        WHERE url = ?
        """,
        (url,),
    ).fetchone()
    if not row:
        return None

    job = dict(row)
    log_detail = load_apply_log_detail(
        job.get("apply_log_path"),
        job_url=job["url"],
        title=job.get("title"),
    )
    job["log_detail"] = log_detail
    return job
