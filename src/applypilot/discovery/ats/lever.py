"""Lever public postings API ingest."""

from __future__ import annotations

import logging

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json
from applypilot.discovery.watchlist import load_watchlist

log = logging.getLogger(__name__)

SITE_PREFIX = "Lever"
STRATEGY = "lever_api"


def fetch_site_jobs(site: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{site}?mode=json"
    data = get_json(url)
    if not isinstance(data, list):
        return []
    jobs: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        job_url = row.get("hostedUrl") or row.get("applyUrl")
        if not job_url:
            continue
        loc = None
        cats = row.get("categories") or {}
        if isinstance(cats, dict):
            loc = cats.get("location")
        full_description = row.get("descriptionPlain")
        jobs.append(
            {
                "url": job_url,
                "application_url": job_url,
                "title": row.get("text"),
                "salary": None,
                "description": full_description,
                "full_description": full_description,
                "location": loc,
            }
        )
    return jobs


def run_lever_discovery(companies: list[dict] | None = None) -> dict:
    init_db()
    conn = get_connection()
    total_fetched = 0
    total_new = 0
    total_dup = 0
    sites = 0
    for company in (companies if companies is not None else load_watchlist()):
        site = (company.get("lever_site") or "").strip()
        if not site:
            continue
        sites += 1
        jobs = fetch_site_jobs(site)
        label = f"{SITE_PREFIX}:{company.get('name', site)}"
        new, dup = store_jobs(conn, jobs, label, STRATEGY)
        total_fetched += len(jobs)
        total_new += new
        total_dup += dup
    log.info("Lever: %d sites, %d jobs, +%d new", sites, total_fetched, total_new)
    return {
        "sites": sites,
        "fetched": total_fetched,
        "new": total_new,
        "duplicate": total_dup,
    }
