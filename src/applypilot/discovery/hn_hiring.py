"""HN Hiring (hnhiring.com) ingest."""

from __future__ import annotations

import logging
import re

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json

log = logging.getLogger(__name__)

SITE = "HN Hiring"
STRATEGY = "hn_hiring_api"

_SENIOR_RE = re.compile(
    r"\b(senior|staff|principal|lead|architect|cto|founding|head|director|manager)\b",
    re.I,
)


def fetch_jobs(*, url: str = "https://hnhiring.com/locations/remote") -> list[dict]:
    data = get_json(url)
    if not isinstance(data, dict):
        return []
    jobs: list[dict] = []
    for month_block in data.values():
        if not isinstance(month_block, dict):
            continue
        for _thread_id, thread in month_block.items():
            if not isinstance(thread, dict):
                continue
            for comment in thread.get("comments") or []:
                if not isinstance(comment, dict):
                    continue
                text = comment.get("text") or ""
                title_line = text.split("\n", 1)[0].strip()
                if not title_line or not _SENIOR_RE.search(title_line):
                    continue
                job_url = comment.get("url") or thread.get("url")
                if not job_url:
                    continue
                jobs.append(
                    {
                        "url": job_url,
                        "title": title_line[:200],
                        "salary": None,
                        "description": text[:4000],
                        "location": "Remote",
                    }
                )
    return jobs


def run_hn_hiring_discovery(*, url: str = "https://hnhiring.com/locations/remote") -> dict:
    init_db()
    conn = get_connection()
    jobs = fetch_jobs(url=url)
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info("HN Hiring: %d fetched, +%d new, %d dup", len(jobs), new, dup)
    return {"fetched": len(jobs), "new": new, "duplicate": dup}
