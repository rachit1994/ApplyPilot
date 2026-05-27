"""Applied jobs API queries."""

from __future__ import annotations

import json
from typing import Any
from applypilot.apply.apply_log_parser import (
    form_filled_from_log_text,
    form_filled_from_stored_json,
    load_apply_log_detail,
)
from applypilot.database import get_connection, init_db


_APPLY_LEDGER_STATUSES = (
    "applied",
    "submitted_unverified",
    "failed",
    "manual",
)


def query_applied_jobs(
    *,
    limit: int = 100,
    offset: int = 0,
    include_failed: bool = False,
    status: str | None = None,
    site: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    init_db()
    conn = get_connection()

    clauses: list[str] = []
    params: list[Any] = []

    if status:
        if status not in _APPLY_LEDGER_STATUSES:
            return [], 0
        clauses.append("apply_status = ?")
        params.append(status)
    elif include_failed:
        placeholders = ", ".join("?" for _ in _APPLY_LEDGER_STATUSES)
        clauses.append(
            f"(apply_status IN ({placeholders}) OR applied_at IS NOT NULL)"
        )
        params.extend(_APPLY_LEDGER_STATUSES)
    else:
        clauses.append("apply_status IN ('applied', 'submitted_unverified')")

    if site:
        clauses.append("site = ?")
        params.append(site)

    if search:
        clauses.append("title LIKE ?")
        params.append(f"%{search}%")

    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM jobs {where}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT url, title, site, location, salary, fit_score,
               application_url, apply_status, apply_error, applied_at,
               last_attempted_at, apply_duration_ms, apply_attempts,
               apply_log_path, verification_confidence, apply_form_filled
        FROM jobs
        {where}
        ORDER BY datetime(COALESCE(applied_at, last_attempted_at)) DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    apps = []
    for row in rows:
        item = dict(row)
        item["form_filled"] = form_filled_from_stored_json(item.pop("apply_form_filled", None))
        apps.append(item)
    return apps, total


def _attach_form_filled(job: dict[str, Any], log_detail: dict[str, Any]) -> dict[str, Any]:
    """Ensure job has form_filled: DB column, else build from log and backfill."""
    stored = form_filled_from_stored_json(job.pop("apply_form_filled", None))
    if stored:
        job["form_filled"] = stored
        return job

    excerpt = log_detail.get("log_excerpt") or ""
    parsed = log_detail.get("parsed") or {}
    if not excerpt and parsed.get("form_filled"):
        job["form_filled"] = parsed["form_filled"]
        return job

    if excerpt:
        built = form_filled_from_log_text(excerpt)
        if built:
            job["form_filled"] = built
            conn = get_connection()
            conn.execute(
                "UPDATE jobs SET apply_form_filled = ? WHERE url = ?",
                (json.dumps(built, ensure_ascii=False), job["url"]),
            )
            conn.commit()
            return job

    if parsed.get("fields"):
        job["form_filled"] = {
            "fields": parsed.get("fields") or [],
            "fill_actions": parsed.get("fill_actions") or [],
            "form_url": parsed.get("form_url"),
            "visible_errors": parsed.get("visible_errors") or [],
            "empty_required": parsed.get("empty_required"),
            "field_count": len(parsed.get("fields") or []),
        }
    else:
        job["form_filled"] = None
    return job


def confirm_application(job_url: str) -> bool:
    """Human confirms a submitted_unverified row is a real application."""
    init_db()
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'applied',
            apply_error = NULL,
            verification_confidence = 'human_confirmed'
        WHERE url = ? AND apply_status = 'submitted_unverified'
        """,
        (job_url,),
    )
    conn.commit()
    return cur.rowcount > 0


def retry_application(job_url: str) -> bool:
    """Clear submitted_unverified so apply can run again on this job."""
    init_db()
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE jobs
        SET apply_status = NULL,
            apply_error = NULL,
            applied_at = NULL
        WHERE url = ? AND apply_status = 'submitted_unverified'
        """,
        (job_url,),
    )
    conn.commit()
    return cur.rowcount > 0


def get_application_detail(job_url: str) -> dict[str, Any] | None:
    init_db()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT url, title, site, location, salary, fit_score, score_reasoning,
               application_url, apply_status, apply_error, applied_at,
               last_attempted_at, apply_duration_ms, apply_attempts,
               apply_log_path, verification_confidence, tailored_resume_path,
               cover_letter_path, apply_form_filled
        FROM jobs
        WHERE url = ?
        """,
        (job_url,),
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
    return _attach_form_filled(job, log_detail)


def query_apply_error_summary() -> list[dict[str, Any]]:
    """Group failed/manual apply outcomes by apply_error for dashboard."""
    init_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT COALESCE(apply_error, '(none)') AS apply_error,
               apply_status,
               COUNT(*) AS count
        FROM jobs
        WHERE apply_status IN ('failed', 'manual')
           OR (apply_error IS NOT NULL AND applied_at IS NULL)
        GROUP BY apply_error, apply_status
        ORDER BY count DESC, apply_error
        """
    ).fetchall()
    return [dict(row) for row in rows]


_NEEDS_HUMAN_ERROR_SUBSTRINGS: tuple[str, ...] = (
    "sso_login_needed",
    "email verification",
    "verify your email",
    "verification needed",
    "pause_for_human",
)


def query_attention_jobs(
    *,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Jobs that need human intervention to complete or confirm.

    Includes:
      - submitted_unverified (needs confirm/retry)
      - manual (manual ATS / no apply URL / user-driven)
      - failed with known human-actionable reasons (SSO/login/email verification)
    Excludes permanent failures with apply_attempts >= 99.
    """
    init_db()
    conn = get_connection()

    like_parts = " OR ".join("LOWER(COALESCE(apply_error,'')) LIKE ?" for _ in _NEEDS_HUMAN_ERROR_SUBSTRINGS)
    like_params = [f"%{s.lower()}%" for s in _NEEDS_HUMAN_ERROR_SUBSTRINGS]

    where = f"""
      WHERE (
        apply_status IN ('submitted_unverified', 'manual')
        OR (
          apply_status = 'failed'
          AND (apply_attempts IS NULL OR apply_attempts < 99)
          AND ({like_parts})
        )
      )
    """

    total = int(conn.execute(f"SELECT COUNT(*) FROM jobs {where}", like_params).fetchone()[0])
    rows = conn.execute(
        f"""
        SELECT url, title, site, location, salary, fit_score,
               application_url, apply_status, apply_error, applied_at,
               last_attempted_at, apply_duration_ms, apply_attempts,
               apply_log_path, verification_confidence, apply_form_filled
        FROM jobs
        {where}
        ORDER BY datetime(COALESCE(last_attempted_at, applied_at)) DESC
        LIMIT ? OFFSET ?
        """,
        (*like_params, limit, offset),
    ).fetchall()

    apps = []
    for row in rows:
        item = dict(row)
        item["form_filled"] = form_filled_from_stored_json(item.pop("apply_form_filled", None))
        apps.append(item)
    return apps, total


def mark_application_applied(job_url: str) -> bool:
    """Human marks an application as completed outside the agent."""
    from datetime import datetime, timezone

    init_db()
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        UPDATE jobs
        SET apply_status = 'applied',
            applied_at = COALESCE(applied_at, ?),
            apply_error = NULL,
            verification_confidence = 'human_marked',
            agent_id = NULL
        WHERE url = ? AND (apply_status IS NULL OR apply_status != 'applied')
        """,
        (now, job_url),
    )
    conn.commit()
    return cur.rowcount > 0


def requeue_application(job_url: str) -> bool:
    """Clear a failed/manual/unverified row so the agent can retry it."""
    init_db()
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE jobs
        SET apply_status = NULL,
            apply_error = NULL,
            applied_at = NULL,
            apply_not_before = NULL,
            agent_id = NULL
        WHERE url = ?
          AND apply_status IN ('failed', 'manual', 'submitted_unverified')
        """,
        (job_url,),
    )
    conn.commit()
    return cur.rowcount > 0
