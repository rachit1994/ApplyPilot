"""Experience-level filters for auto-apply (skip clearly junior roles)."""

from __future__ import annotations

import re

# Roles we never auto-apply to when clearly stated
_JUNIOR_MARKERS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bintern(?:ship)?\b",
        r"\bgraduate\s+(?:scheme|program|role)\b",
        r"\bentry[- ]?level\b",
        r"\bfresher\b",
        r"\bnew\s+grad\b",
        r"\bcampus\s+hire\b",
        r"\b0\s*[-–to]+\s*[12]\s*years?\b",
        r"\b[12]\s*[-–to]+\s*[23]\s*years?\b",
        r"\b(?:min(?:imum)?|at\s+least)\s*[0-4]\s*years?\b",
        r"\b[0-4]\s*\+\s*years?\s+of\s+experience\b",
    )
)

# If any of these appear, do not treat as too-junior despite other signals
_SENIOR_MARKERS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(?:senior|staff|principal|lead|architect|director|head\s+of)\b",
        r"\b(?:5|6|7|8|9|10|12|15)\+?\s*years?\b",
        r"\b[5-9]\s*[-–to]+\s*\d+\s*years?\b",
        r"\b10\+\s*years?\b",
    )
)

_YEARS_RANGE = re.compile(
    r"\b(\d{1,2})\s*[-–to]+\s*(\d{1,2})\s*years?\b",
    re.I,
)
_YEARS_PLUS = re.compile(r"\b(\d{1,2})\+?\s*years?\s+(?:of\s+)?experience\b", re.I)
_MIN_YEARS_REQUIRED = re.compile(
    r"\b(?:min(?:imum)?|at\s+least|requires?)\s*(?:of\s+)?(\d{1,2})\s*(?:\+?\s*)?years?\b",
    re.I,
)
_YEARS_BEFORE_MINIMUM = re.compile(
    r"\b(\d{1,2})\+?\s*years?\s+minimum\b",
    re.I,
)


def _blob(title: str | None, description: str | None) -> str:
    return f"{title or ''} {description or ''}".lower()


def _has_senior_signal(blob: str) -> bool:
    return any(p.search(blob) for p in _SENIOR_MARKERS)


def _max_required_years(blob: str) -> int | None:
    caps: list[int] = []
    for match in _YEARS_RANGE.finditer(blob):
        caps.append(int(match.group(2)))
    for match in _YEARS_PLUS.finditer(blob):
        caps.append(int(match.group(1)))
    if not caps:
        return None
    return max(caps)


def _min_required_years(blob: str) -> int | None:
    """Highest explicit minimum years stated (e.g. 'minimum 5 years')."""
    mins: list[int] = []
    for match in _MIN_YEARS_REQUIRED.finditer(blob):
        mins.append(int(match.group(1)))
    for match in _YEARS_BEFORE_MINIMUM.finditer(blob):
        mins.append(int(match.group(1)))
    if not mins:
        return None
    return max(mins)


def description_satisfies_experience_floor(
    title: str | None,
    description: str | None,
    *,
    min_years: int = 5,
) -> bool:
    """True when the posting targets at least min_years (or senior), not a junior role."""
    blob = _blob(title, description)
    if not blob.strip():
        return False
    if _has_senior_signal(blob):
        return True
    stated_min = _min_required_years(blob)
    if stated_min is not None and stated_min >= min_years:
        return True
    max_years = _max_required_years(blob)
    if max_years is not None and max_years >= min_years:
        return True
    return False


def is_too_junior_role(
    title: str | None,
    description: str | None,
    *,
    min_years: int = 5,
) -> bool:
    """True when the posting clearly targets below min_years experience."""
    blob = _blob(title, description)
    if not blob.strip():
        return False
    if description_satisfies_experience_floor(title, description, min_years=min_years):
        return False
    for pat in _JUNIOR_MARKERS:
        if pat.search(blob):
            return True
    max_years = _max_required_years(blob)
    if max_years is not None and max_years < min_years:
        return True
    return False
