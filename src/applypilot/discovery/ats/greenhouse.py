"""Greenhouse Job Board API ingest."""

from __future__ import annotations

import logging

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json
from applypilot.discovery.watchlist import load_watchlist

log = logging.getLogger(__name__)

SITE_PREFIX = "Greenhouse"
STRATEGY = "greenhouse_api"


def fetch_board_jobs(board: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    data = get_json(url)
    if not isinstance(data, dict):
        return []
    jobs: list[dict] = []
    for row in data.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        job_url = row.get("absolute_url")
        if not job_url:
            continue
        loc = None
        locs = row.get("location") or {}
        if isinstance(locs, dict):
            loc = locs.get("name")
        jobs.append(
            {
                "url": job_url,
                "title": row.get("title"),
                "salary": None,
                "description": None,
                "location": loc,
            }
        )
    return jobs


def run_greenhouse_discovery() -> dict:
    init_db()
    conn = get_connection()
    total_fetched = 0
    total_new = 0
    total_dup = 0
    boards = 0
    for company in load_watchlist():
        board = (company.get("greenhouse_board") or "").strip()
        if not board:
            continue
        boards += 1
        jobs = fetch_board_jobs(board)
        site = f"{SITE_PREFIX}:{company.get('name', board)}"
        new, dup = store_jobs(conn, jobs, site, STRATEGY)
        total_fetched += len(jobs)
        total_new += new
        total_dup += dup
    log.info("Greenhouse: %d boards, %d jobs, +%d new", boards, total_fetched, total_new)
    return {
        "boards": boards,
        "fetched": total_fetched,
        "new": total_new,
        "duplicate": total_dup,
    }
