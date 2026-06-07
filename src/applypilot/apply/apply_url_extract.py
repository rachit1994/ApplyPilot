"""Extract employer ATS apply URLs embedded in job descriptions."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

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


_ACCENTURE_WD_SEARCH = (
    "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs"
)
_ACCENTURE_WD_BASE = "https://accenture.wd103.myworkdayjobs.com"


def _accenture_job_req_id(job_url: str | None) -> str | None:
    """Extract Workday requisition id from an accenture.com jobdetails URL."""
    if not job_url:
        return None
    parsed = urlparse(str(job_url).strip())
    if "accenture.com" not in (parsed.netloc or "").lower():
        return None
    raw_id = (parse_qs(parsed.query).get("id") or [None])[0]
    if not raw_id:
        return None
    req_id = str(raw_id).split("_")[0].strip()
    return req_id or None


def resolve_accenture_workday_apply_url(job_url: str | None) -> str | None:
    """Map accenture.com jobdetails pages to the public Workday posting URL."""
    req_id = _accenture_job_req_id(job_url)
    if not req_id:
        return None
    payload = json.dumps(
        {"appliedFacets": {}, "limit": 5, "offset": 0, "searchText": req_id}
    ).encode()
    req = urllib.request.Request(_ACCENTURE_WD_SEARCH, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; ApplyPilot/1.0)")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    for posting in data.get("jobPostings") or []:
        bullets = posting.get("bulletFields") or []
        external_path = posting.get("externalPath") or ""
        if req_id in bullets or req_id in external_path:
            if external_path.startswith("http"):
                return external_path
            return f"{_ACCENTURE_WD_BASE}{external_path}"
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
