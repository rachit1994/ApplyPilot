"""Wellfound fallback ingest from indexed public result records.

Wellfound can return a CAPTCHA/rate-limit page to local automation. Some public
indexes still expose enough of the Wellfound job page text to include the
employer's explicit ATS apply link. This module ingests those records without an
LLM and preserves Wellfound as the discovery source while storing the executable
ATS URL in ``application_url``.
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

SITE = "Wellfound"
STRATEGY = "wellfound_indexed"
DEFAULT_INDEX_PATH = config.APP_DIR / "wellfound_indexed_jobs.yaml"

_WELLFOUND_JOB_RE = re.compile(r"https?://wellfound\.com/jobs/[^\s\"'<>)\]]+", re.I)
_TITLE_COMPANY_RE = re.compile(r"^(?P<title>.+?)\s+at\s+(?P<company>[^•|\n]+)", re.I)


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _split_title_company(raw_title: str) -> tuple[str, str | None]:
    title = _clean(raw_title)
    if " | Wellfound" in title:
        title = title.split(" | Wellfound", 1)[0].strip()
    match = _TITLE_COMPANY_RE.match(title)
    if not match:
        return title, None
    return _clean(match.group("title")), _clean(match.group("company")) or None


def jobs_from_indexed_records(records: list[dict[str, Any]]) -> list[dict]:
    """Convert search/index result records into ApplyPilot job dicts.

    Each record may have ``title``, ``url``/``href``, and ``snippet``/``text``.
    A row is kept only when it has both a Wellfound job URL and a direct ATS URL
    in the text. That keeps this fallback high-precision and direct-applyable.
    """
    jobs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        title_raw = _clean(record.get("title"))
        blob = "\n".join(
            _clean(record.get(key))
            for key in ("title", "url", "href", "snippet", "text", "description")
        )
        wellfound_url = _clean(record.get("url") or record.get("href"))
        if "wellfound.com/jobs/" not in wellfound_url:
            match = _WELLFOUND_JOB_RE.search(blob)
            wellfound_url = match.group(0).rstrip(".,;") if match else ""
        if not wellfound_url:
            continue
        apply_url = extract_best_apply_url_from_text(blob)
        if not apply_url:
            continue
        title, company = _split_title_company(title_raw)
        if not title:
            title = "Software Engineer"
        key = (wellfound_url, apply_url)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(
            {
                "url": wellfound_url,
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


def run_wellfound_indexed_discovery(
    *,
    index_path: Path | str | None = None,
    records: list[dict[str, Any]] | None = None,
) -> dict:
    """Import direct-ATS Wellfound rows from indexed public result records."""
    init_db()
    conn = get_connection()
    if records is None:
        path = Path(index_path) if index_path else DEFAULT_INDEX_PATH
        records = load_indexed_records(path)
    jobs = jobs_from_indexed_records(records)
    new, dup = store_jobs(conn, jobs, SITE, STRATEGY)
    log.info("Wellfound indexed: %d records, %d direct jobs, +%d new, %d dup",
             len(records), len(jobs), new, dup)
    return {
        "records": len(records),
        "direct_jobs": len(jobs),
        "new": new,
        "duplicate": dup,
    }
