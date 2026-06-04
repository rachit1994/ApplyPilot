"""Pipeline filter stage: cheap relevance gates before LLM scoring."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from applypilot.config import load_profile, load_search_config
from applypilot.database import ensure_columns, get_connection, init_db
from applypilot.scoring.pre_filter import pre_score_filter

log = logging.getLogger(__name__)


def count_pending_filter(conn: sqlite3.Connection | None = None) -> int:
    """Jobs that have not received an algorithmic pre-score yet."""
    if conn is None:
        conn = get_connection()
    ensure_columns(conn)
    return int(
        conn.execute(
            """
            SELECT COUNT(*) FROM jobs
            WHERE fit_score IS NULL
              AND pre_fit_score IS NULL
              AND (
                full_description IS NOT NULL
                OR detail_scraped_at IS NOT NULL
              )
            """
        ).fetchone()[0]
    )


def run_filter(limit: int = 0, conn: sqlite3.Connection | None = None) -> dict[str, int | str]:
    """Pre-score jobs and reject obvious non-fits before LLM scoring.

    Rejected jobs are marked as scored with a low pre-score. Survivors keep
    moving with `pre_fit_score` populated for later LLM ordering.
    """
    own_conn = conn is None
    if conn is None:
        conn = init_db()
    else:
        ensure_columns(conn)

    try:
        try:
            profile = load_profile()
        except FileNotFoundError:
            log.info("Filter skipped: profile.json not found")
            return {"status": "skipped", "checked": 0, "rejected": 0, "kept": 0}

        search_cfg = load_search_config()
        query = """
            SELECT url, title, site, location, salary, description, full_description
            FROM jobs
            WHERE fit_score IS NULL
              AND pre_fit_score IS NULL
              AND (
                full_description IS NOT NULL
                OR detail_scraped_at IS NOT NULL
              )
            ORDER BY discovered_at DESC
        """
        params: list[int] = []
        if limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
        if not rows:
            return {"status": "ok", "checked": 0, "rejected": 0, "kept": 0}

        now = datetime.now(timezone.utc).isoformat()
        checked = rejected = kept = 0
        for row in rows:
            job = dict(row)
            verdict = pre_score_filter(job, profile, search_cfg)
            checked += 1
            if verdict.passes:
                conn.execute(
                    """
                    UPDATE jobs
                    SET pre_fit_score = ?,
                        pre_filter_reason = NULL,
                        pre_filter_rejected_at = NULL
                    WHERE url = ?
                    """,
                    (verdict.pre_score, job["url"]),
                )
                kept += 1
                continue

            reason = verdict.reason or "pre_filter:rejected"
            note = verdict.notes[0] if verdict.notes else reason
            conn.execute(
                """
                UPDATE jobs
                SET pre_fit_score = ?,
                    pre_filter_reason = ?,
                    pre_filter_rejected_at = ?,
                    fit_score = ?,
                    score_reasoning = ?,
                    scored_at = ?,
                    detail_error = ?,
                    detail_scraped_at = ?
                WHERE url = ?
                """,
                (
                    verdict.pre_score,
                    reason,
                    now,
                    verdict.pre_score,
                    f"pre_filter:{reason}\nPre-score: {verdict.pre_score}/10. {note}",
                    now,
                    f"pre_filter:{reason}",
                    now,
                    job["url"],
                ),
            )
            rejected += 1

        conn.commit()
        log.info("Filter checked %d jobs: %d kept, %d rejected", checked, kept, rejected)
        return {
            "status": "ok",
            "checked": checked,
            "rejected": rejected,
            "kept": kept,
        }
    finally:
        if own_conn:
            conn.close()
