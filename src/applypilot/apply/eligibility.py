"""Pre-acquire apply eligibility: classify jobs before launching Claude + Chrome."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from applypilot import config
from applypilot.apply.experience import is_too_junior_role
from applypilot.apply.salary import is_india_focused_job, salary_meets_regional_minimum
from applypilot.apply.apply_url_extract import coerce_application_url
from applypilot.config import DEFAULTS, is_contractor_marketplace, is_manual_ats, load_search_config
from applypilot.discovery._filters import location_passes
from applypilot.discovery.site_priority import job_is_priority_board

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


# High-precision phrases that signal a hard US-residency requirement. Matched
# against the job description only when the candidate is NOT US-based. Kept
# narrow to avoid rejecting roles that merely *mention* the US.
US_RESIDENCY_REQUIRED_PATTERNS: tuple[str, ...] = (
    "must live in a state where",
    "must reside in the united states",
    "must reside within the united states",
    "must be located in the united states",
    "must be located within the united states",
    "must be based in the united states",
    "must be a us resident",
    "must be a u.s. resident",
    "must be a united states resident",
    "you must be located in the u.s.",
    "this position requires you to be located in the united states",
    "open to candidates based in the united states",
)

# Phrases that signal the employer will not sponsor a work visa. Matched only
# when the candidate's profile says they require sponsorship.
NO_SPONSORSHIP_PATTERNS: tuple[str, ...] = (
    "we are unable to sponsor",
    "unable to provide visa sponsorship",
    "unable to sponsor work visas",
    "do not offer visa sponsorship",
    "does not offer visa sponsorship",
    "not offer visa sponsorship",
    "without visa sponsorship",
    "not eligible for visa sponsorship",
    "no visa sponsorship",
    "not provide visa sponsorship",
    "we do not sponsor",
    "does not sponsor",
    "cannot sponsor",
    "will not sponsor",
    "not able to sponsor",
    "without the need for visa sponsorship",
    "without sponsorship now or in the future",
    "not require sponsorship now or in the future",
    "without requiring visa sponsorship",
    "without the need for current or future sponsorship",
)


# Precise US-only tokens. Deliberately excludes bare "America" so multi-country
# regions like "North America, Remote" (which hire internationally) are NOT
# blocked — that string was a real, confirmed application.
_US_LOCATION_RE = re.compile(
    r"\b(?:usa|u\.s\.a\.?|u\.s\.?|us|united\s+states)\b", re.I
)
_CANADA_LOCATION_RE = re.compile(r"\b(?:canada|canadian)\b", re.I)

# Location strings that are open to the candidate regardless of country tags.
_GLOBAL_LOCATION_TOKENS: tuple[str, ...] = (
    "anywhere",
    "worldwide",
    "world wide",
    "global",
    "any location",
    "fully remote",
    "north america",
    "south america",
    "latin america",
    "americas",
    "remote - india",
    "remote india",
    "india remote",
    "remote (india",
    "remote/in",
    "remote-in",
    "work from india",
    "anywhere in india",
    "pan india",
    "pan-india",
)

# Apply-time location accept list for India-based candidates (ignores searches.yaml
# US-centric reject_patterns such as bare "India").
_INDIA_APPLY_LOCATION_ACCEPT: tuple[str, ...] = (
    "india",
    "bengaluru",
    "bangalore",
    "karnataka",
    "hyderabad",
    "telangana",
    "pune",
    "maharashtra",
    "mumbai",
    "chennai",
    "tamil nadu",
    "delhi",
    "new delhi",
    "ncr",
    "national capital region",
    "noida",
    "gurgaon",
    "gurugram",
    "faridabad",
    "ghaziabad",
    "remote - india",
    "remote india",
    "india remote",
    "remote (in",
    "remote/in",
    "remote-in",
    "work from india",
    "anywhere in india",
    "pan india",
    "pan-india",
    "remote",
    "anywhere",
    "work from home",
    "wfh",
    "distributed",
)

# City aliases for matching job location to candidate personal.* fields.
_INDIA_LOCATION_ALIASES: dict[str, tuple[str, ...]] = {
    "bangalore": ("bengaluru", "bangalore"),
    "bengaluru": ("bengaluru", "bangalore"),
    "gurgaon": ("gurgaon", "gurugram"),
    "gurugram": ("gurgaon", "gurugram"),
}


def _candidate_location_facts(profile: dict | None) -> tuple[bool, bool]:
    """Return (us_based, requires_sponsorship) from the candidate profile."""
    prof = _effective_profile(profile)
    personal = prof.get("personal") or {}
    country = str(personal.get("country") or "").strip().lower()
    us_based = country in (
        "us",
        "usa",
        "u.s.",
        "u.s.a.",
        "united states",
        "united states of america",
        "america",
    )
    work_auth = prof.get("work_authorization") or {}
    requires_sponsorship = str(
        work_auth.get("require_sponsorship") or ""
    ).strip().lower() in ("yes", "true", "1", "y")
    return us_based, requires_sponsorship


def _effective_profile(profile: dict | None) -> dict:
    if profile is not None:
        return profile
    try:
        app_dir = Path(os.environ.get("APPLYPILOT_DIR", Path.home() / ".applypilot"))
        profile_path = app_dir / "profile.json"
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def is_india_based_candidate(profile: dict | None) -> bool:
    """True when profile personal.country targets India (not US/other)."""
    us_based, _ = _candidate_location_facts(profile)
    if us_based:
        return False
    prof = _effective_profile(profile)
    personal = prof.get("personal") or {}
    country = str(personal.get("country") or "").strip().lower()
    return country in ("india", "in", "भारत")


def apply_location_passes(
    location: str | None, profile: dict | None = None
) -> bool:
    """Discover-style location filter with India-first overrides at apply time."""
    if is_india_based_candidate(profile):
        return location_passes(
            location,
            accept=list(_INDIA_APPLY_LOCATION_ACCEPT),
            reject=[],
        )
    return location_passes(location)


def _candidate_location_terms(profile: dict | None) -> list[str]:
    """Lowercase location tokens for the candidate (country, city, aliases)."""
    prof = _effective_profile(profile)
    personal = prof.get("personal") or {}
    terms: list[str] = []
    for key in ("country", "city", "province_state"):
        raw = str(personal.get(key) or "").strip().lower()
        if not raw:
            continue
        terms.append(raw)
        for alias_key, aliases in _INDIA_LOCATION_ALIASES.items():
            if raw == alias_key or raw in aliases:
                terms.extend(aliases)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        if term and term not in seen:
            seen.add(term)
            out.append(term)
    return out


def location_restriction_block(location: str | None, profile: dict | None) -> str | None:
    """Detect a country-restricted (e.g. US-only) location the candidate can't take.

    The discover-time ``location_passes`` filter treats anything containing
    "remote" as fine, so "Remote - USA" slips through. For a non-US candidate
    that is a dead end. Returns 'not_eligible_location' or None.
    """
    us_based, _ = _candidate_location_facts(profile)
    if us_based or not location:
        return None
    loc = location.strip().lower()
    if not loc:
        return None
    if any(tok in loc for tok in _GLOBAL_LOCATION_TOKENS):
        return None

    own_terms = _candidate_location_terms(profile)
    if any(term and term in loc for term in own_terms):
        return None

    # Multi-location strings ("Remote - US; Bangalore") are fine if any segment
    # is the candidate's place; that's covered above. Otherwise a clear US tag
    # with no candidate-local segment means US-only. Canada-only remote roles
    # have the same issue for an India-based candidate and often expose only
    # Canadian province choices at apply time.
    if _US_LOCATION_RE.search(loc) or _CANADA_LOCATION_RE.search(loc):
        return "not_eligible_location"
    return None


def description_eligibility_block(
    job: dict, profile: dict | None
) -> str | None:
    """Detect hard location/sponsorship blockers in the job description.

    Returns a skip reason ('not_eligible_location' / 'not_eligible_sponsorship')
    or None. US-based candidates are never filtered by these clauses. For
    India-based candidates, US residency / no-sponsor boilerplate is skipped on
    India-focused roles (domestic market); it still applies on US/global roles.
    """
    us_based, requires_sponsorship = _candidate_location_facts(profile)
    if us_based:
        return None
    if is_india_based_candidate(profile) and is_india_focused_job(
        job.get("location"),
        job.get("full_description"),
        job.get("salary"),
    ):
        return None
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("full_description", "title", "location")
    ).lower()
    if not blob.strip():
        return None
    if any(pat in blob for pat in US_RESIDENCY_REQUIRED_PATTERNS):
        return "not_eligible_location"
    if requires_sponsorship and any(pat in blob for pat in NO_SPONSORSHIP_PATTERNS):
        return "not_eligible_sponsorship"
    return None


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
    return site.startswith(("greenhouse:", "lever:", "ashby:"))


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


def priority_boards_only_enabled() -> bool:
    import os

    raw = os.environ.get("APPLYPILOT_PRIORITY_BOARDS_ONLY", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    use_strict = strict if strict is not None else _queue_mode() != "all_tailored"
    min_exp = min_experience_years if min_experience_years is not None else int(
        DEFAULTS.get("apply_min_experience_years", 5)
    )

    raw_app = coerce_application_url(job.get("application_url"))
    raw_url = coerce_application_url(job.get("url"))
    apply_url = (raw_app or raw_url or "").strip()
    if apply_url and not raw_app:
        job = {**job, "application_url": apply_url}
    url_blob = (job.get("url") or "") + (job.get("application_url") or "")
    title = job.get("title")

    if priority_boards_only_enabled() and not job_is_priority_board(job):
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "non_priority_board")

    # LinkedIn is marked manual in config/sites.yaml, but some LinkedIn job pages
    # expose an "Apply on company website" button that leads to an external ATS.
    # Let those flow through the apply agent, which can click out to the company
    # site and then apply there.
    if "linkedin.com/jobs" in url_blob.lower():
        return EligibilityResult(ApplyDecision.ELIGIBLE, "linkedin_company_website_flow")

    if is_manual_ats(apply_url):
        return EligibilityResult(ApplyDecision.MANUAL, "manual ATS")

    if is_contractor_marketplace(apply_url):
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "not_a_job_application")

    if not apply_url:
        return EligibilityResult(ApplyDecision.MANUAL, "no_apply_url")

    if job.get("location") and not apply_location_passes(
        job.get("location"), profile
    ):
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, "not_eligible_location")

    # "Remote - USA" passes location_passes (it contains "remote") but is a dead
    # end for a non-US candidate. Catch country-restricted remote here.
    loc_block = location_restriction_block(job.get("location"), profile)
    if loc_block:
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, loc_block)

    # The `location` column is often just "Remote"; the real US-only / no-sponsor
    # restriction can also live in the description. Catch it here so neither the
    # Claude nor the Direct engine wastes a session on an impossible job.
    desc_block = description_eligibility_block(job, profile)
    if desc_block:
        return EligibilityResult(ApplyDecision.SKIP_PERMANENT, desc_block)

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


def summarize_eligibility_classification(
    jobs: list[dict],
    *,
    profile: dict | None = None,
    **classify_kwargs,
) -> dict[str, int]:
    """Count classify_apply_target outcomes (before/after eligibility tuning)."""
    counts: dict[str, int] = {}
    for job in jobs:
        result = classify_apply_target(job, profile=profile, **classify_kwargs)
        label = (
            f"{result.decision.value}:{result.reason}"
            if result.reason
            else result.decision.value
        )
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def direct_adapter_priority_sql() -> str:
    """SQL CASE: 0 = active Playwright direct adapter, 1 = needs Claude/manual."""
    from applypilot.apply import apply_settings

    excluded = apply_settings.direct_excluded_families()
    parts = ["CASE"]
    if "greenhouse" not in excluded:
        parts.append(
            "WHEN LOWER(COALESCE(site, '')) LIKE 'greenhouse:%' "
            "OR LOWER(COALESCE(url, '')) LIKE '%greenhouse.io%' "
            "OR LOWER(COALESCE(application_url, '')) LIKE '%greenhouse.io%' "
            "OR LOWER(COALESCE(full_description, '')) LIKE '%greenhouse.io%' "
            "OR LOWER(COALESCE(url, '')) LIKE '%grnh.se%' "
            "OR LOWER(COALESCE(application_url, '')) LIKE '%grnh.se%' "
            "OR LOWER(COALESCE(full_description, '')) LIKE '%grnh.se%' "
            "OR LOWER(COALESCE(application_url, url, '')) LIKE '%gh_jid=%' "
            "OR LOWER(COALESCE(application_url, url, full_description, '')) LIKE '%gh_jid&%' "
            "OR LOWER(COALESCE(full_description, '')) LIKE '%gh_jid=%' THEN 0"
        )
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) LIKE 'lever:%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%lever.co%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%lever.co%' "
        "OR LOWER(COALESCE(full_description, '')) LIKE '%lever.co%' "
        "OR LOWER(COALESCE(application_url, url, '')) LIKE '%lever-source=%' "
        "OR LOWER(COALESCE(application_url, url, full_description, '')) LIKE '%lever-source=%' "
        "OR LOWER(COALESCE(application_url, url, '')) LIKE '%lever_source=%' "
        "OR LOWER(COALESCE(application_url, url, full_description, '')) LIKE '%lever_source=%' THEN 0"
    )
    if "ashby" not in excluded:
        parts.append(
            "WHEN LOWER(COALESCE(site, '')) LIKE 'ashby:%' "
            "OR LOWER(COALESCE(url, '')) LIKE '%ashbyhq.com%' "
            "OR LOWER(COALESCE(application_url, '')) LIKE '%ashbyhq.com%' "
            "OR LOWER(COALESCE(full_description, '')) LIKE '%ashbyhq.com%' THEN 0"
        )
    parts.append(
        "WHEN LOWER(COALESCE(application_url, url, '')) LIKE '%workatastartup.com%' "
        "OR LOWER(COALESCE(full_description, '')) LIKE '%workatastartup.com%' THEN 0"
    )
    parts.append("ELSE 1 END")
    return " ".join(parts)


def ats_priority_sql_case() -> str:
    """SQL CASE expression: lower sort key = higher priority."""
    parts = ["CASE"]
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) LIKE 'greenhouse:%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%greenhouse.io%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%greenhouse.io%' THEN 0"
    )
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) LIKE 'lever:%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%lever.co%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%lever.co%' THEN 1"
    )
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) LIKE 'ashby:%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%ashbyhq.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%ashbyhq.com%' THEN 2"
    )
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) = 'linkedin' "
        "OR LOWER(COALESCE(site, '')) = 'linkedin.com' "
        "OR LOWER(COALESCE(url, '')) LIKE '%linkedin.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%linkedin.com%' THEN 3"
    )
    parts.append(
        "WHEN LOWER(COALESCE(site, '')) = 'wellfound' "
        "OR LOWER(COALESCE(url, '')) LIKE '%wellfound.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%wellfound.com%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%angel.co%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%angel.co%' THEN 4"
    )
    for marker in ATS_URL_MARKERS:
        parts.append(
            f"WHEN LOWER(COALESCE(application_url, '')) LIKE '%{marker}%' THEN 5"
        )
    parts.append(
        "WHEN LOWER(COALESCE(application_url, url, '')) LIKE '%workatastartup.com%' THEN 6"
    )
    parts.append("ELSE 7 END")
    return " ".join(parts)


def priority_boards_only_where_clause() -> str:
    """Extra WHERE fragment: ATS-first, LinkedIn, and Wellfound jobs only."""
    return (
        "AND ("
        "LOWER(COALESCE(site, '')) LIKE 'greenhouse:%' "
        "OR LOWER(COALESCE(site, '')) LIKE 'lever:%' "
        "OR LOWER(COALESCE(site, '')) LIKE 'ashby:%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%greenhouse.io%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%greenhouse.io%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%lever.co%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%lever.co%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%ashbyhq.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%ashbyhq.com%' "
        "OR LOWER(COALESCE(site, '')) = 'linkedin' "
        "OR LOWER(COALESCE(site, '')) = 'linkedin.com' "
        "OR LOWER(COALESCE(url, '')) LIKE '%linkedin.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%linkedin.com%' "
        "OR LOWER(COALESCE(site, '')) = 'wellfound' "
        "OR LOWER(COALESCE(url, '')) LIKE '%wellfound.com%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%wellfound.com%' "
        "OR LOWER(COALESCE(url, '')) LIKE '%angel.co%' "
        "OR LOWER(COALESCE(application_url, '')) LIKE '%angel.co%'"
        ")"
    )


def excluded_ats_families_where_clause() -> str:
    """Exclude jobs whose apply URL maps to APPLYPILOT_SKIP_ATS_FAMILIES (e.g. greenhouse, ashby)."""
    from applypilot.apply import apply_settings

    excluded = apply_settings.direct_excluded_families()
    if not excluded:
        return ""
    neg: list[str] = []
    if "greenhouse" in excluded:
        neg.extend(
            [
                "LOWER(COALESCE(application_url, url, '')) NOT LIKE '%greenhouse.io%'",
                "LOWER(COALESCE(application_url, url, '')) NOT LIKE '%grnh.se%'",
                "LOWER(COALESCE(site, '')) NOT LIKE 'greenhouse:%'",
            ]
        )
    if "ashby" in excluded:
        neg.extend(
            [
                "LOWER(COALESCE(application_url, url, '')) NOT LIKE '%ashbyhq.com%'",
                "LOWER(COALESCE(site, '')) NOT LIKE 'ashby:%'",
            ]
        )
    if not neg:
        return ""
    return "AND (" + " AND ".join(neg) + ")"


def ats_only_where_clause() -> str:
    """Extra WHERE fragment when --ats-only: ATS apply URL or Work at a Startup."""
    likes = " OR ".join(
        f"LOWER(COALESCE(application_url, '')) LIKE '%{m}%' "
        f"OR LOWER(COALESCE(full_description, '')) LIKE '%{m}%'"
        for m in ATS_URL_MARKERS
    )
    return (
        f"AND ({likes} "
        "OR LOWER(COALESCE(site, '')) LIKE 'greenhouse:%' "
        "OR LOWER(COALESCE(site, '')) LIKE 'lever:%' "
        "OR LOWER(COALESCE(site, '')) LIKE 'ashby:%' "
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
