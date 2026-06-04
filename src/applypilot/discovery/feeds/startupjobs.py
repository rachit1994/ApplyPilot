"""StartupJobs fallback ingest from indexed public result records.

StartupJobs can sit behind bot mitigation for local automation. This fallback
accepts search/index records that already include snippets from public job pages,
keeps only records with a StartupJobs job URL plus an executable direct apply
URL, and stores that direct URL in ``application_url``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from applypilot import config
from applypilot.apply.apply_url_extract import extract_best_apply_url_from_text
from applypilot.database import get_connection, init_db, store_jobs

log = logging.getLogger(__name__)

SITE = "StartupJobs"
STRATEGY = "startupjobs_indexed"
DEFAULT_INDEX_PATH = config.APP_DIR / "startupjobs_indexed_jobs.yaml"

_STARTUPJOBS_JOB_RE = re.compile(
    r"https?://(?:www\.)?startup\.jobs/[^\s\"'<>)\]]+", re.I
)
_TITLE_COMPANY_RE = re.compile(r"^(?P<title>.+?)\s+at\s+(?P<company>[^•|\n]+)", re.I)


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _split_title_company(raw_title: str) -> tuple[str, str | None]:
    title = _clean(raw_title)
    for suffix in (" | Startup Jobs", " - Startup Jobs", " | StartupJobs"):
        if suffix in title:
            title = title.split(suffix, 1)[0].strip()
    match = _TITLE_COMPANY_RE.match(title)
    if not match:
        return title, None
    return _clean(match.group("title")), _clean(match.group("company")) or None


def _startupjobs_url_from_record(record: dict[str, Any], blob: str) -> str:
    url = _clean(record.get("url") or record.get("href"))
    if "startup.jobs/" in url:
        return url.rstrip(".,;")
    match = _STARTUPJOBS_JOB_RE.search(blob)
    return match.group(0).rstrip(".,;") if match else ""


def jobs_from_indexed_records(records: list[dict[str, Any]]) -> list[dict]:
    """Convert indexed StartupJobs records into direct-applyable job dicts."""
    jobs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        title_raw = _clean(record.get("title"))
        blob = "\n".join(
            _clean(record.get(key))
            for key in ("title", "url", "href", "snippet", "text", "description")
        )
        startupjobs_url = _startupjobs_url_from_record(record, blob)
        if not startupjobs_url:
            continue
        apply_url = extract_best_apply_url_from_text(blob)
        if not apply_url:
            continue
        title, company = _split_title_company(title_raw)
        if not title:
            title = "Software Engineer"
        key = (startupjobs_url, apply_url)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(
            {
                "url": startupjobs_url,
                "title": title,
                "company": company,
                "description": _clean(record.get("snippet") or record.get("text"))[:2000],
                "full_description": blob,
                "application_url": apply_url,
                "location": _clean(record.get("location")) or None,
            }
        )
    return jobs


def load_indexed_records(path: Path | str) -> list[dict[str, Any]]:
    """Load indexed records from JSON/YAML list or newline-delimited JSON."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = None
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            records.append(row)
    return records


def run_startupjobs_indexed_discovery(
    *,
    index_path: Path | str | None = None,
    records: list[dict[str, Any]] | None = None,
) -> dict:
    """Import direct-applyable StartupJobs rows from indexed public records."""
    init_db()
    conn = get_connection()
    if records is None:
        path = Path(index_path) if index_path else DEFAULT_INDEX_PATH
        records = load_indexed_records(path)
    jobs = jobs_from_indexed_records(records)
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info(
        "StartupJobs indexed: %d records, %d direct jobs, +%d new, %d dup",
        len(records), len(jobs), new, dup,
    )
    return {
        "records": len(records),
        "direct_jobs": len(jobs),
        "new": new,
        "duplicate": dup,
    }
