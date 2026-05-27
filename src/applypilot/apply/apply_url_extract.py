"""Extract employer ATS apply URLs embedded in job descriptions."""

from __future__ import annotations

import re

# Hosts the apply agent can navigate (Workday, Greenhouse, Lever, etc.)
_ATS_HOST_FRAGMENTS = (
    "myworkdayjobs.com",
    "workday.com",
    "boards.greenhouse.io",
    "greenhouse.io",
    "jobs.lever.co",
    "lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "icims.com",
    "smartrecruiters.com",
    "jobvite.com",
    "bamboohr.com",
    "workable.com",
    "apply.workable.com",
    "taleo.net",
    "successfactors.com",
    "oraclecloud.com",
    "grnh.se",
    "workatastartup.com",
)

_URL_IN_TEXT = re.compile(
    r"https?://[^\s\"'<>)\]]+",
    re.IGNORECASE,
)


def _is_ats_host(url: str) -> bool:
    lower = url.lower()
    return any(fragment in lower for fragment in _ATS_HOST_FRAGMENTS)


def _clean_url(url: str) -> str:
    cleaned = url.rstrip(".,;:)\"'")
    if cleaned.endswith("%2C") or cleaned.endswith("%2c"):
        cleaned = cleaned[:-3]
    return cleaned


def extract_best_apply_url_from_text(text: str | None) -> str | None:
    """Return the first ATS apply URL found in free text, or None."""
    if not text or not str(text).strip():
        return None
    for match in _URL_IN_TEXT.finditer(str(text)):
        candidate = _clean_url(match.group(0))
        if _is_ats_host(candidate):
            return candidate
    return None


def coerce_application_url(value: str | None) -> str | None:
    """Normalize JobSpy/DB placeholders to a real URL or None."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in {"none", "nan", "null", "n/a"}:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return None
