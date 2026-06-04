"""Cheap pre-score filter — reject obvious mismatches before paying Gemini."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from applypilot.apply.experience import description_satisfies_experience_floor
from applypilot.apply.salary import salary_meets_regional_minimum
from applypilot.config import DEFAULTS, get_target_roles, load_search_config

# Stable config keys → rejection reason codes stored on jobs.
FILTER_CHECK_KEYS: tuple[str, ...] = (
    "title_junior_or_intern",
    "title_exec_non_eng",
    "title_adjacent_role",
    "title_allowlist",
    "location",
    "salary_floor",
    "blocked_keywords",
    "description_junior_signal",
    "profile_keyword_overlap",
)

FILTER_CHECK_REASONS: dict[str, str] = {
    "title_junior_or_intern": "title:junior_or_intern",
    "title_exec_non_eng": "title:exec_non_eng",
    "title_adjacent_role": "title:adjacent_role",
    "title_allowlist": "title:not_in_allowlist",
    "location": "location:reject_pattern",
    "salary_floor": "salary:below_floor",
    "blocked_keywords": "description:blocked_keyword",
    "description_junior_signal": "description:junior_signal",
    "profile_keyword_overlap": "profile:low_keyword_overlap",
}

_REASON_TO_CHECK_KEY: dict[str, str] = {
    reason: key for key, reason in FILTER_CHECK_REASONS.items()
}

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
_NEGATED_BEFORE_BAD = re.compile(
    r"\b(?:not|non|no)\s+[-]?\s*$",
    re.I,
)


@dataclass(frozen=True)
class PreFilterVerdict:
    passes: bool
    reason: str | None
    pre_score: int
    notes: tuple[str, ...] = ()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "enable", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disable", "disabled"):
        return False
    return bool(value)


def _normalize_filter_check_key(raw: str) -> str | None:
    key = str(raw).strip()
    if not key:
        return None
    if key in FILTER_CHECK_REASONS:
        return key
    if key in _REASON_TO_CHECK_KEY:
        return _REASON_TO_CHECK_KEY[key]
    return _REASON_TO_CHECK_KEY.get(key.replace("-", "_"))


def _filter_section(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {}
    section = cfg.get("filter")
    if isinstance(section, dict):
        return section
    legacy = cfg.get("pre_filter")
    return legacy if isinstance(legacy, dict) else {}


def resolve_filter_checks(
    search_cfg: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Merge per-check toggles from searches.yaml and profile.json fit_filters."""
    checks = {key: True for key in FILTER_CHECK_KEYS}

    for container in (_filter_section(search_cfg), (profile or {}).get("fit_filters") or {}):
        if not isinstance(container, dict):
            continue
        raw_checks = container.get("checks")
        if isinstance(raw_checks, dict):
            for raw_key, enabled in raw_checks.items():
                key = _normalize_filter_check_key(str(raw_key))
                if key:
                    checks[key] = _coerce_bool(enabled)
        for raw_key in container.get("disable") or []:
            key = _normalize_filter_check_key(str(raw_key))
            if key:
                checks[key] = False

    return checks


def pre_filter_disabled(
    search_cfg: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> bool:
    if os.environ.get("APPLYPILOT_DISABLE_PRE_FILTER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    for container in (_filter_section(search_cfg), (profile or {}).get("fit_filters") or {}):
        if isinstance(container, dict) and container.get("enabled") is False:
            return True
    return False


def pre_score_filter(
    job: dict,
    profile: dict,
    search_cfg: dict | None = None,
) -> PreFilterVerdict:
    """Return verdict for one job. Pure function aside from optional env bypass."""
    cfg = search_cfg if search_cfg is not None else load_search_config()
    if pre_filter_disabled(cfg, profile):
        return PreFilterVerdict(True, None, 7, ("pre-filter disabled",))

    checks = resolve_filter_checks(cfg, profile)
    title = (job.get("title") or "").strip()
    raw_description = (
        job.get("full_description")
        or job.get("description")
        or ""
    )
    description = str(raw_description)[:5000]
    text = f"{title}\n{description}".lower()
    location = (job.get("location") or "").strip()
    salary = (job.get("salary") or "").strip()
    notes: list[str] = []

    def reject(reason: str, score: int, note: str) -> PreFilterVerdict:
        return PreFilterVerdict(False, reason, max(1, min(10, score)), (note,))

    if checks["title_junior_or_intern"] and SENIORITY_BAD.search(title):
        return reject("title:junior_or_intern", 1, "Title is junior, intern, trainee, or entry-level.")
    if checks["title_exec_non_eng"] and EXEC_ROLES.search(title):
        return reject("title:exec_non_eng", 2, "Title is an executive non-engineering role.")
    if checks["title_adjacent_role"] and ADJACENT_NONENG.search(title):
        return reject("title:adjacent_role", 3, "Title points to sales, solutions, product, or customer-success work.")

    includes = [
        str(s).lower()
        for s in (cfg.get("include_titles") or [])
        if str(s).strip()
    ]
    if (
        checks["title_allowlist"]
        and includes
        and not any(s in title.lower() for s in includes)
    ):
        return reject("title:not_in_allowlist", 3, "Title does not match the configured target title allowlist.")

    from applypilot.config import load_location_filter_patterns
    from applypilot.discovery._filters import location_passes

    accept, reject_patterns = load_location_filter_patterns(cfg)
    if (
        checks["location"]
        and location
        and not location_passes(location, accept=accept, reject=reject_patterns)
    ):
        return PreFilterVerdict(
            False,
            "location:reject_pattern",
            1,
            ("Location is outside the configured accepted/remote regions.",),
        )

    salary_ok = True
    if checks["salary_floor"] and salary and not salary_meets_regional_minimum(
        salary, description, location, profile=profile
    ):
        return PreFilterVerdict(
            False,
            "salary:below_floor",
            2,
            ("Salary appears below the configured regional floor.",),
        )
    if checks["salary_floor"] and salary:
        salary_ok = salary_meets_regional_minimum(
            salary, description, location, profile=profile
        )

    blocked = _configured_blocked_keywords(cfg, profile)
    if checks["blocked_keywords"]:
        blocked_hit = next((kw for kw in blocked if kw.lower() in text), None)
        if blocked_hit:
            return reject(
                "description:blocked_keyword",
                1,
                f"JD contains blocked keyword: {blocked_hit}.",
            )

    min_exp_years = int(DEFAULTS.get("apply_min_experience_years", 5))
    if (
        checks["description_junior_signal"]
        and not SENIORITY_GOOD.search(title)
        and not description_satisfies_experience_floor(
            title, description, min_years=min_exp_years
        )
        and _description_has_junior_signal(description)
    ):
        return reject("description:junior_signal", 3, "JD text contains junior or entry-level signals.")

    score = 5
    title_lower = title.lower()
    if SENIORITY_GOOD.search(title):
        score += 2
        notes.append("senior/lead title signal")

    role_hits = _target_role_hits(title_lower, profile)
    if role_hits:
        score += min(2, len(role_hits))
        notes.append(f"title matches target role: {', '.join(role_hits[:3])}")

    skill_hits = _profile_keyword_hits(text, profile)
    if skill_hits:
        score += 1 if len(skill_hits) < 3 else 2
        notes.append(f"profile keyword overlap: {', '.join(skill_hits[:5])}")

    if checks["location"] and location:
        score += 1
        notes.append("location accepted")
    if checks["salary_floor"] and salary and salary_ok:
        score += 1
        notes.append("salary passed floor")

    has_enough_jd = len(description) >= 350
    if (
        checks["profile_keyword_overlap"]
        and has_enough_jd
        and not role_hits
        and len(skill_hits) < 2
    ):
        return PreFilterVerdict(
            False,
            "profile:low_keyword_overlap",
            min(score, 4),
            ("JD has too little overlap with target roles and profile skills.",),
        )

    return PreFilterVerdict(True, None, max(1, min(10, score)), tuple(notes))


def _description_has_junior_signal(description: str) -> bool:
    """True when JD has junior/entry-level signals that are not negated (e.g. 'not entry-level')."""
    for match in SENIORITY_BAD.finditer(description):
        prefix = description[max(0, match.start() - 16) : match.start()]
        if _NEGATED_BEFORE_BAD.search(prefix):
            continue
        return True
    return False


def _configured_blocked_keywords(cfg: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """Collect explicit no-go words from config/profile without requiring one schema."""
    candidates: list[Any] = []
    for key in ("exclude_keywords", "blocked_keywords", "deny_keywords", "not_allowed_keywords"):
        candidates.extend(cfg.get(key) or [])

    filters = profile.get("fit_filters") or {}
    for key in ("exclude_keywords", "blocked_keywords", "deny_keywords", "not_allowed_keywords"):
        candidates.extend(filters.get(key) or [])

    out: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if text and text.lower() not in {x.lower() for x in out}:
            out.append(text)
    return out


def _target_role_hits(title_lower: str, profile: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for role in get_target_roles(profile):
        role_lower = role.lower()
        tokens = [t for t in re.split(r"[^a-z0-9+#.]+", role_lower) if len(t) >= 3]
        if role_lower in title_lower or (tokens and sum(t in title_lower for t in tokens) >= min(2, len(tokens))):
            hits.append(role)
    return hits


def _flatten_profile_keywords(profile: dict[str, Any]) -> list[str]:
    raw: list[Any] = []
    skills = profile.get("skills_boundary") or {}
    if isinstance(skills, dict):
        for values in skills.values():
            if isinstance(values, list):
                raw.extend(values)
            else:
                raw.append(values)

    for role in get_target_roles(profile):
        raw.extend(re.split(r"[^a-zA-Z0-9+#.]+", role))

    facts = profile.get("resume_facts") or {}
    for key in ("preserved_projects", "preserved_companies"):
        values = facts.get(key) or []
        if isinstance(values, list):
            raw.extend(values)

    keywords: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip()
        if len(text) < 3:
            continue
        key = text.lower()
        if key not in seen:
            keywords.append(text)
            seen.add(key)
    return keywords


def _profile_keyword_hits(text_lower: str, profile: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for keyword in _flatten_profile_keywords(profile):
        if keyword.lower() in text_lower:
            hits.append(keyword)
    return hits[:12]
