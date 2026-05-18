"""LinkedIn public identifier helpers."""

from __future__ import annotations

import re

_IN_SLUG = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)


def public_id_from_url(url: str | None) -> str | None:
    """Extract vanity slug from a LinkedIn profile URL."""
    if not url:
        return None
    match = _IN_SLUG.search(url)
    if not match:
        return None
    slug = match.group(1).strip("/").lower()
    if slug in ("", "me"):
        return None
    return slug


def is_linkedin_job_url(url: str | None) -> bool:
    if not url:
        return False
    lower = url.lower()
    return "linkedin.com/jobs" in lower or "linkedin.com/job" in lower


def job_linkedin_url(row: dict) -> str | None:
    """Best LinkedIn job page URL for a jobs row."""
    for key in ("url", "application_url"):
        value = row.get(key)
        if value and is_linkedin_job_url(value):
            return value
    site = (row.get("site") or "").lower()
    if "linkedin" in site and row.get("url"):
        return row["url"]
    return None
