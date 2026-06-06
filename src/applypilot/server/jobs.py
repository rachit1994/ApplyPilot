"""Job listing endpoints for the dashboard."""

from __future__ import annotations

from typing import Any

from applypilot import config
from applypilot.apply.eligibility import ats_priority_sql_case
from applypilot.database import get_connection, init_db
from applypilot.server.job_pipeline_stage import (
    resolve_stage_label,
    stage_filter_clause,
)
from applypilot.server.job_present import present_job_row
from applypilot.server.job_triage import normalize_triage_slug, triage_filter_clause
from applypilot.server.low_score_reason import low_score_reason_filter_clause

_PIPELINE_STAGES: dict[str, str] = {
    "tailored": "tailored_resume_path IS NOT NULL",
    "ready": (
        "tailored_resume_path IS NOT NULL "
        "AND applied_at IS NULL "
        "AND (apply_status IS NULL OR apply_status = 'failed') "
        "AND (apply_attempts IS NULL OR apply_attempts < ?)"
    ),
    "applied": "apply_status = 'applied'",
}

_SORT_ORDERS: dict[str, str] = {
    "activity_desc": "datetime(COALESCE(scored_at, discovered_at)) DESC, COALESCE(fit_score, 0) DESC",
    "activity_asc": "datetime(COALESCE(scored_at, discovered_at)) ASC, COALESCE(fit_score, 0) ASC",
    "fit_score_desc": "COALESCE(fit_score, 0) DESC, datetime(COALESCE(scored_at, discovered_at)) DESC",
    "fit_score_asc": "COALESCE(fit_score, 0) ASC, datetime(COALESCE(scored_at, discovered_at)) DESC",
    "discovered_at_desc": "discovered_at DESC",
    "discovered_at_asc": "discovered_at ASC",
    "scored_at_desc": "COALESCE(scored_at, '') DESC, discovered_at DESC",
    "scored_at_asc": "COALESCE(scored_at, '') ASC, discovered_at ASC",
    "title_asc": "COALESCE(title, '') ASC",
    "title_desc": "COALESCE(title, '') DESC",
    "apply_priority": f"{ats_priority_sql_case()}, COALESCE(fit_score, 0) DESC, url",
}

def _escape_like_pattern(raw: str) -> str:
    """Escape SQL LIKE wildcards so user input is matched literally."""
    escaped = raw.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_JOB_SELECT_COLUMNS = """
    url, title, site, location, salary, strategy, fit_score, score_reasoning,
    score_role_key, score_jd_fit,
    pre_fit_score, pre_filter_reason, pre_filter_rejected_at,
    discovered_at, scored_at, detail_error, full_description,
    detail_scraped_at, application_url,
    tailored_resume_path, tailored_at, tailor_attempts,
    cover_letter_path, cover_letter_at, cover_attempts,
    applied_at, apply_status, apply_error, apply_attempts,
    last_attempted_at, verification_confidence,
    COALESCE(scored_at, discovered_at) AS activity_at
"""


def build_jobs_filter(
    *,
    min_score: int | None = None,
    site: str | None = None,
    search: str | None = None,
    pipeline_stage: str | None = None,
    stage: str | None = None,
    apply_status: str | None = None,
    low_score_reason: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Shared WHERE fragments for job list + triage chip counts."""
    clauses: list[str] = []
    params: list[Any] = []

    if min_score is not None and min_score > 0:
        clauses.append("fit_score >= ?")
        params.append(min_score)
    if site:
        clauses.append("site = ?")
        params.append(site)
    if apply_status:
        clauses.append("apply_status = ?")
        params.append(apply_status.strip())

    stage_raw = (stage or "").strip()
    triage_slug = normalize_triage_slug(stage_raw)
    if triage_slug:
        clauses.append(triage_filter_clause(triage_slug))
    elif stage_raw:
        stage_label = resolve_stage_label(stage)
        if stage_label:
            clauses.append(stage_filter_clause(stage_label))
        else:
            clauses.append("1=0")
    else:
        stage_key = (pipeline_stage or "").strip().lower()
        if stage_key in _PIPELINE_STAGES:
            clause = _PIPELINE_STAGES[stage_key]
            clauses.append(clause)
            if stage_key == "ready":
                params.append(config.DEFAULTS["max_apply_attempts"])

    if search:
        q = _escape_like_pattern(search)
        clauses.append(
            "(title LIKE ? ESCAPE '\\' OR site LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\' "
            "OR description LIKE ? ESCAPE '\\' OR full_description LIKE ? ESCAPE '\\')"
        )
        params.extend([q, q, q, q, q])

    reason_clause = low_score_reason_filter_clause(low_score_reason)
    if reason_clause:
        clauses.append(reason_clause)

    return clauses, params


def count_jobs_matching(clauses: list[str], params: list[Any]) -> int:
    init_db()
    conn = get_connection()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()
    return int(row[0] if row else 0)


def fetch_triage_counts_filtered(
    *,
    min_score: int | None = None,
    site: str | None = None,
    search: str | None = None,
    apply_status: str | None = None,
    low_score_reason: str | None = None,
) -> dict[str, int]:
    """Per-chip counts using the same extra filters as GET /api/jobs (not global stats)."""
    from applypilot.server.job_triage import TRIAGE_SLUGS, triage_filter_clause

    base_clauses, base_params = build_jobs_filter(
        min_score=min_score,
        site=site,
        search=search,
        apply_status=apply_status,
        low_score_reason=low_score_reason,
    )
    counts: dict[str, int] = {
        "all": count_jobs_matching(base_clauses, base_params),
    }
    for slug in sorted(TRIAGE_SLUGS):
        slug_clauses = [*base_clauses, triage_filter_clause(slug)]
        counts[slug] = count_jobs_matching(slug_clauses, base_params)
    return counts


def resolve_jobs_pagination(
    *,
    limit: int,
    offset: int = 0,
    page: int | None = None,
    total: int = 0,
) -> tuple[int, int, int, int]:
    """Return (limit, offset, page, pages) for GET /api/jobs."""
    limit = min(max(limit, 1), 500)
    if page is not None and page >= 1:
        current_page = page
        offset = (page - 1) * limit
    else:
        offset = max(0, offset)
        current_page = (offset // limit) + 1 if limit else 1
    pages = (total + limit - 1) // limit if total > 0 else 0
    if pages and current_page > pages:
        current_page = pages
        offset = (current_page - 1) * limit
    return limit, offset, current_page, pages


def query_jobs(
    *,
    min_score: int | None = None,
    site: str | None = None,
    search: str | None = None,
    pipeline_stage: str | None = None,
    stage: str | None = None,
    apply_status: str | None = None,
    low_score_reason: str | None = None,
    sort: str = "activity_desc",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    init_db()
    conn = get_connection()
    clauses, params = build_jobs_filter(
        min_score=min_score,
        site=site,
        search=search,
        pipeline_stage=pipeline_stage,
        stage=stage,
        apply_status=apply_status,
        low_score_reason=low_score_reason,
    )

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM jobs {where}", params
    ).fetchone()[0]

    order_by = _SORT_ORDERS.get(sort, _SORT_ORDERS["activity_desc"])
    rows = conn.execute(
        f"""
        SELECT {_JOB_SELECT_COLUMNS}
        FROM jobs
        {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    jobs = [present_job_row(dict(row)) for row in rows]
    return jobs, total


def query_recent_jobs(minutes: int = 60, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT {_JOB_SELECT_COLUMNS}
        FROM jobs
        WHERE (
            discovered_at >= datetime('now', ?)
            OR scored_at >= datetime('now', ?)
        )
        ORDER BY COALESCE(scored_at, discovered_at) DESC
        LIMIT ?
        """,
        (f"-{minutes} minutes", f"-{minutes} minutes", limit),
    ).fetchall()
    return [present_job_row(dict(row)) for row in rows]
