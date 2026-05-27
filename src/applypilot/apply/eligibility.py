"""Pre-acquire apply eligibility: classify jobs before launching Claude + Chrome."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from applypilot import config
from applypilot.apply.experience import is_too_junior_role
from applypilot.apply.salary import salary_meets_regional_minimum
from applypilot.apply.apply_url_extract import coerce_application_url
from applypilot.config import DEFAULTS, is_contractor_marketplace, is_manual_ats, load_search_config

# Known ATS hosts — auto-apply priority queue
ATS_URL_MARKERS: tuple[str, ...] = (
    "greenhouse.io",
    "boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "icims.com",
    "smartrecruiters.com",
    "jobvite.com",
    "bamboohr.com",
    "applytojob.com",
    "recruitee.com",
    "teamtailor.com",
    "breezy.hr",
    "rippling.com",
    "paylocity.com",
)

# Title substrings that indicate gig/marketplace listings (not employer ATS forms)
GIG_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\$\s*\d+\s*/\s*hr",
        r"\d+\s*/\s*hr\b",
        r"\bhourly\b",
        r"\bAI\s+Training\b",
        r"\btraining\s+specialist\b",
        r"\bdata\s+label",
        r"\bannotation\b",
        r"\bfreelance\b",
        r"\bcontract\s+only\b",
        r"\bgig\b",
        r"\btask\s+rater\b",
        r"\bcrowd\s*source",
    )
)


class ApplyDecision(str, Enum):
    ELIGIBLE = "eligible"
    MANUAL = "manual"
    SKIP_PERMANENT = "skip_permanent"


@dataclass(frozen=True)
class EligibilityResult:
    decision: ApplyDecision
    reason: str | None = None


def load_exclude_title_substrings() -> list[str]:
    """Title exclude list from searches.yaml (discover only; not used in apply classify)."""
    from applypilot.discovery._filters import load_title_filters

    excludes, _includes = load_title_filters()
    return excludes


def is_workatastartup_job(job: dict) -> bool:
    url = (job.get("url") or "") + (job.get("application_url") or "")
    strategy = (job.get("strategy") or "").lower()
    return "workatastartup.com" in url.lower() or strategy == "workatastartup"


def is_ats_sourced_job(job: dict) -> bool:
    site = (job.get("site") or "").lower()
    return site.startswith("greenhouse:") or site.startswith("lever:")


def is_ats_url(url: str | None) -> bool:
    if not url:
        return False
    lower = url.lower()
    return any(marker in lower for marker in ATS_URL_MARKERS)


def _title_is_hourly_gig(title: str | None) -> bool:
    if not title:
        return False
    lower = title.lower()
    return any(pat.search(lower) for pat in GIG_TITLE_PATTERNS)


def _queue_mode() -> str:
    return str(DEFAULTS.get("apply_queue_mode", "all_tailored"))


def classify_apply_target(
    job: dict,
    *,
    ats_only: bool = False,
    min_experience_years: int | None = None,
    profile: dict | None = None,
    strict: bool | None = None,
) -> EligibilityResult:
    """Classify whether a tailored job should enter the auto-apply agent queue.

    Default ``all_tailored`` mode only blocks non-apply surfaces (manual ATS,
    contractor marketplaces, missing URL). Salary (40 LPA / $70k) and experience
    are enforced by the browser agent via the prompt, not pre-acquire DB skips.
    Set ``strict=True`` (triage preview) to apply salary/experience filters up front.
    """
    _ = profile
    use_strict = strict if strict is not None else _queue_mode() != "all_tailored"
    min_exp = min_experience_years if min_experience_years is not None else int(
        DEFAULTS.get("apply_min_experience_years", 5)
    )

    raw_app = coerce_application_url(job.get("application_url"))
    raw_url = coerce_application_url(job.get("url"))
    apply_url = (raw_app or raw_url or "").strip()
    if apply_url and not raw_app:
        job = {**job, "application_url": apply_url}
    title = job.get("title")

    if is_manual_ats(apply_url):
        return EligibilityResult(ApplyDecision.MANUAL, "manual ATS")

    if is_contractor_marketplace(apply_url):
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "not_a_job_application")

    if not apply_url:
        return EligibilityResult(ApplyDecision.MANUAL, "no_apply_url")

    if (
        ats_only
        and not is_ats_url(apply_url)
        and not is_ats_sourced_job(job)
        and not is_workatastartup_job(job)
    ):
        return EligibilityResult(ApplyDecision.MANUAL, "non_ats_url")

    if not use_strict:
        return EligibilityResult(ApplyDecision.ELIGIBLE, None)

    if _title_is_hourly_gig(title):
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "not_eligible_salary")

    if is_workatastartup_job(job):
        return EligibilityResult(ApplyDecision.ELIGIBLE, None)

    if is_too_junior_role(
        title,
        job.get("full_description"),
        min_years=min_exp,
    ):
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "not_eligible_experience")

    salary_ok = salary_meets_regional_minimum(
        job.get("salary"),
        job.get("full_description"),
        job.get("location"),
    )
    if not salary_ok:
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "not_eligible_salary")

    return EligibilityResult(ApplyDecision.ELIGIBLE, None)


def ats_priority_sql_case() -> str:
    """SQL CASE expression: lower sort key = higher priority."""
    parts = ["CASE"]
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) = 'naukri' "
        "OR LOWER(COALESCE(url, '')) LIKE '%naukri.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%naukri.com%' THEN 0"
    )
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) = 'wellfound' "
        "OR LOWER(COALESCE(url, '')) LIKE '%wellfound.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%wellfound.com%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%angel.co%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%angel.co%' THEN 1"
    )
    for marker in ATS_URL_MARKERS:
        parts.append(
            f"WHEN LOWER(COALESCE(application_url, '')) LIKE '%{marker}%' THEN 2"
        )
    parts.append(
        "WHEN LOWER(COALESCE(application_url, url, '')) LIKE '%workatastartup.com%' THEN 3"
    )
    parts.append("ELSE 4 END")
    return " ".join(parts)


def ats_only_where_clause() -> str:
    """Extra WHERE fragment when --ats-only: ATS apply URL or Work at a Startup."""
    likes = " OR ".join(
        f"LOWER(COALESCE(application_url, '')) LIKE '%{m}%'" for m in ATS_URL_MARKERS
    )
    return (
        f"AND ({likes} "
        "OR LOWER(COALESCE(site, '')) LIKE 'greenhouse:%' "
        "OR LOWER(COALESCE(site, '')) LIKE 'lever:%' "
        "OR LOWER(COALESCE(application_url, url, '')) LIKE '%workatastartup.com%')"
    )


def check_yc_login_configured() -> tuple[bool, str]:
    """Whether profile has credentials for Work at a Startup login."""
    try:
        profile = config.load_profile()
    except Exception as exc:
        return False, f"profile error: {exc}"
    personal = profile.get("personal") or {}
    email = (personal.get("email") or "").strip()
    password = (personal.get("password") or "").strip()
    if not email:
        return False, "profile.json missing personal.email"
    if not password:
        return (
            False,
            "profile.json missing personal.password (needed for account.ycombinator.com)",
        )
    return True, f"YC login configured for {email}"
