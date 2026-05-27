"""Himalayas job board API ingest."""

from __future__ import annotations

import logging

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json

log = logging.getLogger(__name__)

SITE = "Himalayas"
STRATEGY = "himalayas_api"


def fetch_jobs(*, limit: int = 50) -> list[dict]:
    data = get_json("https://himalayas.app/jobs/api")
    if not isinstance(data, list):
        return []
    jobs: list[dict] = []
    for row in data[:limit]:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug")
        if not slug:
            continue
        url = f"https://himalayas.app/jobs/{slug}"
        jobs.append(
            {
                "url": url,
                "title": row.get("title"),
                "salary": row.get("minSalary") and f"{row.get('minSalary')}-{row.get('maxSalary')}",
                "description": row.get("excerpt"),
                "location": (row.get("locationRestrictions") or ["Remote"])[0]
                if isinstance(row.get("locationRestrictions"), list)
                else "Remote",
            }
        )
    return jobs


def run_himalayas_discovery(*, limit: int = 50) -> dict:
    init_db()
    conn = get_connection()
    jobs = fetch_jobs(limit=limit)
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info("Himalayas: %d fetched, +%d new, %d dup", len(jobs), new, dup)
    return {"fetched": len(jobs), "new": new, "duplicate": dup}
