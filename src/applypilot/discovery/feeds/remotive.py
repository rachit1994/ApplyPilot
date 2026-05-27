"""Remotive public API ingest."""

from __future__ import annotations

import logging

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json

log = logging.getLogger(__name__)

SITE = "Remotive"
STRATEGY = "remotive_api"


def fetch_jobs() -> list[dict]:
    data = get_json("https://remotive.com/api/remote-jobs")
    if not isinstance(data, dict):
        return []
    rows = data.get("jobs") or []
    jobs: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        if not url:
            continue
        jobs.append(
            {
                "url": url,
                "title": row.get("title"),
                "salary": row.get("salary"),
                "description": row.get("description"),
                "location": row.get("candidate_required_location") or "Remote",
            }
        )
    return jobs


def run_remotive_discovery() -> dict:
    init_db()
    conn = get_connection()
    jobs = fetch_jobs()
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info("Remotive: %d fetched, +%d new, %d dup", len(jobs), new, dup)
    return {"fetched": len(jobs), "new": new, "duplicate": dup}
