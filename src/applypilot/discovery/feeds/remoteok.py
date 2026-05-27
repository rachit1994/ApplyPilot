"""Remote OK public API ingest."""

from __future__ import annotations

import logging
from html import unescape
import re

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json

log = logging.getLogger(__name__)

SITE = "Remote OK"
STRATEGY = "remoteok_api"


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", unescape(text))
    return re.sub(r"\s+", " ", cleaned).strip() or None


def fetch_jobs(*, tags: str = "dev") -> list[dict]:
    url = f"https://remoteok.com/api?tags={tags}"
    data = get_json(url)
    if not isinstance(data, list):
        return []
    jobs: list[dict] = []
    for row in data:
        if not isinstance(row, dict) or row.get("id") == "ok":
            continue
        job_url = row.get("url") or row.get("apply_url")
        if not job_url:
            continue
        salary = None
        if row.get("salary_min") or row.get("salary_max"):
            salary = f"{row.get('salary_min', '')}-{row.get('salary_max', '')} {row.get('salary_currency', '')}".strip()
        jobs.append(
            {
                "url": job_url,
                "title": row.get("position") or row.get("title"),
                "salary": salary,
                "description": _strip_html(row.get("description")),
                "location": row.get("location") or "Remote",
            }
        )
    return jobs


def run_remoteok_discovery(*, tags: str = "dev") -> dict:
    init_db()
    conn = get_connection()
    jobs = fetch_jobs(tags=tags)
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info("Remote OK: %d fetched, +%d new, %d dup", len(jobs), new, dup)
    return {"fetched": len(jobs), "new": new, "duplicate": dup}
