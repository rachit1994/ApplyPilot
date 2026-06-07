"""Shared formatting for per-job pipeline log lines."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from applypilot.database import get_connection

_URL_SUFFIX_RE = re.compile(r" \| (https?://\S+)\s*$")
_URL_COLON_RE = re.compile(r"\bURL:\s*(https?://\S+)", re.IGNORECASE)


def extract_job_url_from_message(message: str | None) -> str | None:
    """Parse job URL from format_job_line or apply worker log lines."""
    if not message:
        return None
    text = message.strip()
    match = _URL_SUFFIX_RE.search(text)
    if match:
        return match.group(1).rstrip(".,;)")
    match = _URL_COLON_RE.search(text)
    if match:
        return match.group(1).rstrip(".,;)")
    return None


def format_job_line(
    job: dict[str, Any] | None = None,
    *,
    title: str | None = None,
    url: str | None = None,
    site: str | None = None,
    title_max: int = 45,
    url_max: int = 120,
) -> str:
    """Human-readable job label for logs: title @ site | url."""
    if job:
        title = job.get("title") or title
        url = job.get("url") or url
        site = job.get("site") or site
    label = (title or "untitled").strip()
    if len(label) > title_max:
        label = label[: title_max - 1].rstrip() + "…"
    site_name = (site or "").strip()
    if site_name:
        label = f"{label} @ {site_name}"
    job_url = (url or "").strip()
    if len(job_url) > url_max:
        job_url = job_url[: url_max - 3].rstrip() + "..."
    if job_url:
        return f"{label} | {job_url}"
    return label


def lookup_job_by_artifact(path: Path | str, conn=None) -> dict[str, str] | None:
    """Resolve a tailored/cover text path back to a job row, if known."""
    if conn is None:
        conn = get_connection()
    candidates: list[str] = []
    raw = Path(path)
    candidates.append(str(raw))
    try:
        candidates.append(str(raw.resolve()))
    except OSError:
        pass
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        row = conn.execute(
            """
            SELECT url, title, site FROM jobs
            WHERE tailored_resume_path = ? OR cover_letter_path = ?
            LIMIT 1
            """,
            (candidate, candidate),
        ).fetchone()
        if row:
            return {"url": row["url"], "title": row["title"] or "", "site": row["site"] or ""}
    return None
