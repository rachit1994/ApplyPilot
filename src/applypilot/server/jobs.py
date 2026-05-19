"""Job listing endpoints for the dashboard."""

from __future__ import annotations

from typing import Any

from applypilot.database import get_connection, init_db

_SORT_ORDERS: dict[str, str] = {
    "activity_desc": "datetime(COALESCE(scored_at, discovered_at)) DESC, COALESCE(fit_score, 0) DESC",
    "fit_score_desc": "COALESCE(fit_score, 0) DESC, datetime(COALESCE(scored_at, discovered_at)) DESC",
    "fit_score_asc": "COALESCE(fit_score, 0) ASC, datetime(COALESCE(scored_at, discovered_at)) DESC",
    "discovered_at_desc": "discovered_at DESC",
    "discovered_at_asc": "discovered_at ASC",
    "scored_at_desc": "COALESCE(scored_at, '') DESC, discovered_at DESC",
    "title_asc": "COALESCE(title, '') ASC",
}


def query_jobs(
    *,
    min_score: int | None = None,
    site: str | None = None,
    search: str | None = None,
    sort: str = "activity_desc",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    init_db()
    conn = get_connection()
    clauses: list[str] = []
    params: list[Any] = []

    if min_score is not None:
        clauses.append("fit_score >= ?")
        params.append(min_score)
    if site:
        clauses.append("site = ?")
        params.append(site)
    if search:
        q = f"%{search}%"
        clauses.append(
            "(title LIKE ? OR site LIKE ? OR description LIKE ? OR location LIKE ?)"
        )
        params.extend([q, q, q, q])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM jobs {where}", params
    ).fetchone()[0]

    order_by = _SORT_ORDERS.get(sort, _SORT_ORDERS["fit_score_desc"])
    rows = conn.execute(
        f"""
        SELECT url, title, site, location, salary, fit_score, score_reasoning,
               discovered_at, scored_at, detail_error,
               COALESCE(scored_at, discovered_at) AS activity_at
        FROM jobs
        {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    jobs = [dict(row) for row in rows]
    return jobs, total


def query_recent_jobs(minutes: int = 60, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT url, title, site, location, salary, fit_score, score_reasoning,
               discovered_at, scored_at, detail_error,
               COALESCE(scored_at, discovered_at) AS activity_at
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
    return [dict(row) for row in rows]
