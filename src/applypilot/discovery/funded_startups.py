"""Funded startup discovery targets for smart extraction.

The official YC company directory at https://www.ycombinator.com/companies is
React-rendered and not a stable JSON API, so this source uses the community
YC dataset first:
https://raw.githubusercontent.com/antoniordf/yc-companies/main/yc_companies.json

If that community JSON is unavailable, keep this source empty and defer the
interactive fallback to the slower agent_browse path in a follow-up.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from applypilot.discovery.feeds._http import get_json

log = logging.getLogger(__name__)

YC_COMPANIES_URL = "https://raw.githubusercontent.com/antoniordf/yc-companies/main/yc_companies.json"
DEFAULT_BATCHES = ("W26", "S25", "W25", "S24", "W24")
DEFAULT_CAREER_PATHS = ("careers", "jobs")


def _rows_from_payload(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("companies", "results", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _normalize_website(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = f"https:{value}"
    elif not re.match(r"^https?://", value, re.I):
        value = f"https://{value}"

    parsed = urlparse(value)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}".rstrip("/")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def parse_yc_companies(
    payload: object,
    *,
    batches: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Extract company name, website, and batch from a flexible YC JSON shape."""
    wanted_batches = {b.upper() for b in (batches or []) if b}
    companies: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for row in _rows_from_payload(payload):
        name = _text(row, "name", "company", "company_name")
        website = _normalize_website(_text(row, "website", "website_url", "url", "domain"))
        batch = _text(row, "batch", "yc_batch", "batch_name").upper()
        if not name or not website:
            continue
        if wanted_batches and batch and batch not in wanted_batches:
            continue

        key = (name.lower(), website.lower())
        if key in seen:
            continue
        seen.add(key)
        companies.append({"name": name, "website": website, "batch": batch})
        if limit and len(companies) >= limit:
            break

    return companies


def career_sites_for_company(
    company: dict[str, str],
    *,
    career_paths: list[str] | tuple[str, ...] = DEFAULT_CAREER_PATHS,
    include_greenhouse: bool = True,
) -> list[dict[str, str]]:
    """Return likely career-page URLs for one funded startup without touching disk."""
    name = company.get("name", "").strip()
    website = _normalize_website(company.get("website", ""))
    if not name or not website:
        return []

    sites: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for raw_path in career_paths:
        path = str(raw_path).strip().strip("/")
        if not path:
            continue
        url = f"{website}/{path}"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sites.append(
            {
                "name": f"YC:{name}",
                "url": url,
                "type": "static",
                "mode": "smartextract",
                "source": "funded_startups",
            }
        )

    if include_greenhouse:
        parsed = urlparse(website)
        domain_slug = _slugify(parsed.netloc.removeprefix("www.").split(".")[0])
        name_slug = _slugify(name)
        for slug in (domain_slug, name_slug):
            if not slug:
                continue
            url = f"https://boards.greenhouse.io/{slug}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            sites.append(
                {
                    "name": f"YC:{name} Greenhouse",
                    "url": url,
                    "type": "static",
                    "mode": "smartextract",
                    "source": "funded_startups",
                }
            )

    return sites


def build_funded_startup_sites(cfg: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Fetch the YC community dataset and build in-memory smart-extract sites."""
    cfg = cfg or {}
    dataset_url = str(cfg.get("dataset_url") or YC_COMPANIES_URL)
    batches = cfg.get("batches") or DEFAULT_BATCHES
    limit = int(cfg.get("limit", 50))
    career_paths = cfg.get("career_paths") or DEFAULT_CAREER_PATHS
    include_greenhouse = bool(cfg.get("include_greenhouse", True))
    max_sites = int(cfg.get("max_sites", 150))

    try:
        payload = get_json(dataset_url, timeout=float(cfg.get("timeout", 30.0)))
    except Exception as exc:
        log.warning(
            "Funded startup YC dataset unavailable (%s); agent_browse fallback is deferred",
            exc,
        )
        return []

    companies = parse_yc_companies(payload, batches=batches, limit=limit)
    sites: list[dict[str, str]] = []
    for company in companies:
        sites.extend(
            career_sites_for_company(
                company,
                career_paths=career_paths,
                include_greenhouse=include_greenhouse,
            )
        )
        if max_sites and len(sites) >= max_sites:
            return sites[:max_sites]

    return sites
