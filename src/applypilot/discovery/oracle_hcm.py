"""Oracle HCM Candidate Experience job discovery via public REST API."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import yaml

from applypilot.config import CONFIG_DIR
from applypilot.db.connection import Connection
from applypilot.db.dialect import is_unique_violation
from applypilot.database import get_connection, init_db
from applypilot.discovery._filters import discover_job_passes

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; ApplyPilot/1.0)"


def load_portals() -> dict[str, dict[str, Any]]:
    path = CONFIG_DIR / "oracle_hcm.yaml"
    if not path.exists():
        log.warning("oracle_hcm.yaml not found at %s", path)
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("portals") or {}


def _job_ui_url(portal: dict[str, Any], req_id: str) -> str:
    host = portal["host"]
    site = portal["site_number"]
    locale = portal.get("locale") or "en"
    return (
        f"https://{host}/hcmUI/CandidateExperience/{locale}/sites/{site}/job/{req_id}"
    )


def _list_api_url(portal: dict[str, Any], *, offset: int, limit: int) -> str:
    host = portal["host"]
    site = portal["site_number"]
    finder_parts = [
        f"siteNumber={site}",
        "facetsList=LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;"
        "CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS",
        f"limit={limit}",
        f"offset={offset}",
        "sortBy=POSTING_DATES_DESC",
    ]
    if portal.get("selected_categories_facet"):
        finder_parts.append(
            f"selectedCategoriesFacet={portal['selected_categories_facet']}"
        )
    if portal.get("selected_posting_dates_facet"):
        finder_parts.append(
            f"selectedPostingDatesFacet={portal['selected_posting_dates_facet']}"
        )
    finder = f"findReqs;{','.join(finder_parts)}"
    qs = urllib.parse.urlencode({"onlyData": "true", "expand": "all", "finder": finder})
    return f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?{qs}"


def _detail_api_url(portal: dict[str, Any], req_id: str) -> str:
    host = portal["host"]
    site = portal["site_number"]
    finder = f"ById;Id={req_id},siteNumber={site}"
    qs = urllib.parse.urlencode({"onlyData": "true", "finder": finder})
    return (
        f"https://{host}/hcmRestApi/resources/latest/"
        f"recruitingCEJobRequisitionDetails?{qs}"
    )


def _fetch_json(url: str, *, timeout: float = 45.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_requisitions(portal: dict[str, Any]) -> list[dict[str, Any]]:
    page_size = int(portal.get("page_size") or 100)
    offset = 0
    all_reqs: list[dict[str, Any]] = []
    total: int | None = None

    while True:
        url = _list_api_url(portal, offset=offset, limit=page_size)
        payload = _fetch_json(url)
        items = payload.get("items") or []
        if not items:
            break
        block = items[0]
        if total is None:
            total = int(block.get("TotalJobsCount") or 0)
        batch = block.get("requisitionList") or []
        if not batch:
            break
        all_reqs.extend(batch)
        offset += len(batch)
        if total and offset >= total:
            break
        if len(batch) < page_size:
            break
        time.sleep(0.15)

    return all_reqs


def _fetch_description(portal: dict[str, Any], req_id: str) -> str:
    try:
        payload = _fetch_json(_detail_api_url(portal, req_id))
        item = (payload.get("items") or [{}])[0]
        return str(item.get("ExternalDescriptionStr") or "").strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        log.debug("Oracle detail fetch failed for %s: %s", req_id, exc)
        return ""


def _store_jobs(
    conn: Connection,
    jobs: list[dict[str, Any]],
    *,
    site_name: str,
) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0

    for job in jobs:
        url = job.get("url") or ""
        if not url:
            continue
        description = job.get("description") or ""
        short_desc = description[:500] if description else None
        full_description = description if len(description) > 200 else None
        detail_scraped_at = now if full_description else None

        try:
            conn.execute(
                "INSERT INTO jobs (url, title, salary, description, location, site, strategy, "
                "discovered_at, full_description, application_url, detail_scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    job.get("title"),
                    None,
                    short_desc,
                    job.get("location"),
                    site_name,
                    "oracle_hcm_api",
                    now,
                    full_description,
                    url,
                    detail_scraped_at,
                ),
            )
            new += 1
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            conn.execute(
                "UPDATE jobs SET title = ?, location = ?, site = ?, strategy = ?, "
                "description = COALESCE(?, description), "
                "full_description = COALESCE(?, full_description), "
                "application_url = COALESCE(?, application_url), "
                "detail_scraped_at = COALESCE(?, detail_scraped_at) "
                "WHERE url = ?",
                (
                    job.get("title"),
                    job.get("location"),
                    site_name,
                    "oracle_hcm_api",
                    short_desc,
                    full_description,
                    url,
                    detail_scraped_at,
                    url,
                ),
            )
            existing += 1

    conn.commit()
    return new, existing


def discover_portal(portal_key: str, portal: dict[str, Any]) -> dict[str, int]:
    site_name = portal.get("name") or portal_key
    log.info("Oracle HCM: listing jobs for %s (%s)", site_name, portal_key)
    reqs = _fetch_requisitions(portal)
    log.info("Oracle HCM: %s returned %d requisitions", site_name, len(reqs))

    jobs: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for req in reqs:
        req_id = str(req.get("Id") or "").strip()
        if not req_id:
            continue
        title = str(req.get("Title") or "").strip()
        location = str(req.get("PrimaryLocation") or "").strip()
        if not discover_job_passes({"title": title, "location": location}):
            continue
        candidates.append(req)

    log.info("Oracle HCM: %s — %d/%d pass title/location filters", site_name, len(candidates), len(reqs))

    for idx, req in enumerate(candidates, 1):
        req_id = str(req.get("Id") or "").strip()
        title = str(req.get("Title") or "").strip()
        location = str(req.get("PrimaryLocation") or "").strip()
        short = str(req.get("ShortDescriptionStr") or "").strip()
        url = _job_ui_url(portal, req_id)
        desc = _fetch_description(portal, req_id)
        if idx % 20 == 0:
            time.sleep(0.2)
        if not desc and short:
            desc = short
        jobs.append(
            {
                "url": url,
                "title": title,
                "location": location,
                "description": desc,
            }
        )

    conn = get_connection()
    new, existing = _store_jobs(conn, jobs, site_name=site_name)
    log.info(
        "Oracle HCM: %s stored new=%d existing=%d (listed=%d)",
        site_name,
        new,
        existing,
        len(jobs),
    )
    return {"found": len(jobs), "new": new, "existing": existing, "queries": 1}


def run_oracle_hcm_discovery(portals: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Discover jobs from configured Oracle HCM CE portals."""
    init_db()
    if portals is None:
        portals = load_portals()
    if not portals:
        return {"found": 0, "new": 0, "existing": 0, "queries": 0}

    total_found = 0
    total_new = 0
    total_existing = 0
    for key, portal in portals.items():
        try:
            stats = discover_portal(key, portal)
        except Exception as exc:
            log.error("Oracle HCM portal %s failed: %s", key, exc)
            continue
        total_found += stats.get("found", 0)
        total_new += stats.get("new", 0)
        total_existing += stats.get("existing", 0)

    return {
        "found": total_found,
        "new": total_new,
        "existing": total_existing,
        "queries": len(portals),
    }
