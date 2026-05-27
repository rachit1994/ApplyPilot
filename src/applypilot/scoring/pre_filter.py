"""Cheap pre-score filter — reject obvious mismatches before paying Gemini."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from applypilot.apply.salary import salary_meets_regional_minimum
from applypilot.config import load_search_config

SENIORITY_BAD = re.compile(
    r"\b(intern|internship|junior|jr\b|entry[\s-]?level|graduate|trainee|fresher|"
    r"0[-\s]?(1|2|3)\s*years?|0[-\s]?3\+?\s*yrs?)\b",
    re.I,
)
SENIORITY_GOOD = re.compile(
    r"\b(senior|staff|principal|lead|architect|head\s+of)\b",
    re.I,
)
EXEC_ROLES = re.compile(
    r"\b(chief\s+(financial|operating|marketing|revenue|legal|people)|"
    r"vp\s+of|director\s+of\s+(sales|marketing|hr))\b",
    re.I,
)
ADJACENT_NONENG = re.compile(
    r"\b(sales\s+engineer|solutions?\s+engineer|pre[-\s]?sales|"
    r"customer\s+success|product\s+manager|business\s+analyst)\b",
    re.I,
)


@dataclass(frozen=True)
class PreFilterVerdict:
    passes: bool
    reason: str | None


def pre_filter_disabled() -> bool:
    return os.environ.get("APPLYPILOT_DISABLE_PRE_FILTER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def pre_score_filter(
    job: dict,
    profile: dict,
    search_cfg: dict | None = None,
) -> PreFilterVerdict:
    """Return verdict for one job. Pure function aside from optional env bypass."""
    if pre_filter_disabled():
        return PreFilterVerdict(True, None)

    cfg = search_cfg if search_cfg is not None else load_search_config()
    title = (job.get("title") or "").strip()
    description = (job.get("full_description") or "")[:3000]
    location = (job.get("location") or "").strip()
    salary = (job.get("salary") or "").strip()

    if SENIORITY_BAD.search(title):
        return PreFilterVerdict(False, "title:junior_or_intern")
    if EXEC_ROLES.search(title):
        return PreFilterVerdict(False, "title:exec_non_eng")
    if ADJACENT_NONENG.search(title):
        return PreFilterVerdict(False, "title:adjacent_role")

    includes = [
        str(s).lower()
        for s in (cfg.get("include_titles") or [])
        if str(s).strip()
    ]
    if includes and not any(s in title.lower() for s in includes):
        return PreFilterVerdict(False, "title:not_in_allowlist")

    from applypilot.config import load_location_filter_patterns
    from applypilot.discovery._filters import location_passes

    accept, reject = load_location_filter_patterns(cfg)
    if location and not location_passes(location, accept=accept, reject=reject):
        return PreFilterVerdict(False, "location:reject_pattern")

    if salary and not salary_meets_regional_minimum(
        salary, description, location, profile=profile
    ):
        return PreFilterVerdict(False, "salary:below_floor")

    if not SENIORITY_GOOD.search(title) and SENIORITY_BAD.search(description):
        return PreFilterVerdict(False, "description:junior_signal")

    return PreFilterVerdict(True, None)
