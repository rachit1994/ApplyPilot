"""Ashby public job board API ingest."""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from applypilot.database import get_connection, init_db, store_jobs
from applypilot.discovery.feeds._http import get_json
from applypilot.discovery.watchlist import load_watchlist

log = logging.getLogger(__name__)

SITE_PREFIX = "Ashby"
STRATEGY = "ashby_api"


def _clean_html(value: str | None) -> str | None:
    if not value:
        return None
    return BeautifulSoup(value, "html.parser").get_text("\n", strip=True)


def _format_compensation(row: dict) -> str | None:
    comps = row.get("compensation") or row.get("compensationTiers")
    if not isinstance(comps, list) or not comps:
        return None
    parts: list[str] = []
    for comp in comps[:3]:
        if not isinstance(comp, dict):
            continue
        summary = comp.get("summary") or comp.get("compensationType")
        if summary:
            parts.append(str(summary))
    return "; ".join(parts) if parts else None


def _format_location(row: dict) -> str | None:
    locations: list[str] = []
    primary = row.get("location")
    if primary:
        locations.append(str(primary))
    for loc in row.get("secondaryLocations") or []:
        if isinstance(loc, str):
            locations.append(loc)
        elif isinstance(loc, dict) and loc.get("location"):
            locations.append(str(loc["location"]))
    workplace_type = str(row.get("workplaceType") or "").strip().lower()
    is_explicit_remote = workplace_type == "remote" or any(
        "remote" in x.lower() for x in locations
    )
    if is_explicit_remote and not any("remote" in x.lower() for x in locations):
        locations.append("Remote")
    return ", ".join(dict.fromkeys(locations)) if locations else None


def fetch_board_jobs(board: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
    data = get_json(url)
    if not isinstance(data, dict):
        return []
    jobs: list[dict] = []
    for row in data.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        job_url = row.get("jobUrl") or row.get("applyUrl")
        apply_url = row.get("applyUrl") or job_url
        if not job_url:
            continue
        full_description = row.get("descriptionPlain") or _clean_html(row.get("descriptionHtml"))
        jobs.append(
            {
                "url": job_url,
                "application_url": apply_url,
                "title": row.get("title"),
                "salary": _format_compensation(row),
                "description": full_description,
                "full_description": full_description,
                "location": _format_location(row),
            }
        )
    return jobs


def run_ashby_discovery() -> dict:
    init_db()
    conn = get_connection()
    total_fetched = 0
    total_new = 0
    total_dup = 0
    boards = 0
    for company in load_watchlist():
        board = (
            company.get("ashby_board")
            or company.get("ashby_site")
            or ""
        ).strip()
        if not board:
            continue
        boards += 1
        jobs = fetch_board_jobs(board)
        site = f"{SITE_PREFIX}:{company.get('name', board)}"
        new, dup = store_jobs(conn, jobs, site, STRATEGY)
        total_fetched += len(jobs)
        total_new += new
        total_dup += dup
    log.info("Ashby: %d boards, %d jobs, +%d new", boards, total_fetched, total_new)
    return {
        "boards": boards,
        "fetched": total_fetched,
        "new": total_new,
        "duplicate": total_dup,
    }
