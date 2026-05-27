"""Shared discover-time title and location filters from searches.yaml."""

from __future__ import annotations

from functools import lru_cache

from applypilot.config import load_location_filter_patterns, load_search_config


@lru_cache(maxsize=1)
def load_title_filters() -> tuple[list[str], list[str]]:
    """Return (exclude_substrings, include_substrings), lowercase."""
    cfg = load_search_config()
    excludes = [
        str(x).strip().lower()
        for x in (cfg.get("exclude_titles") or [])
        if str(x).strip()
    ]
    includes = [
        str(x).strip().lower()
        for x in (cfg.get("include_titles") or [])
        if str(x).strip()
    ]
    return excludes, includes


def clear_filter_cache() -> None:
    """Reset cached search config (for tests)."""
    load_title_filters.cache_clear()
    _cached_location_patterns.cache_clear()


@lru_cache(maxsize=1)
def _cached_location_patterns() -> tuple[list[str], list[str]]:
    return load_location_filter_patterns()


def title_passes(
    title: str | None,
    *,
    excludes: list[str] | None = None,
    includes: list[str] | None = None,
) -> bool:
    if not title:
        return True
    lower = title.lower()
    if excludes is None and includes is None:
        ex, inc = load_title_filters()
    else:
        ex = [s.lower() for s in (excludes or [])]
        inc = [s.lower() for s in (includes or [])]

    if any(sub in lower for sub in ex):
        return False
    if inc and not any(sub in lower for sub in inc):
        return False
    return True


def location_passes(
    location: str | None,
    *,
    accept: list[str] | None = None,
    reject: list[str] | None = None,
) -> bool:
    if accept is None or reject is None:
        accept_p, reject_p = _cached_location_patterns()
        accept = accept if accept is not None else accept_p
        reject = reject if reject is not None else reject_p

    if not location:
        return True

    loc = location.lower()
    if any(
        r in loc
        for r in ("remote", "anywhere", "work from home", "wfh", "distributed")
    ):
        return True

    for r in reject:
        if r.lower() in loc:
            return False

    for a in accept:
        if a.lower() in loc:
            return True

    return False


def discover_job_passes(job: dict) -> bool:
    """Apply title + location filters before persisting a discovered job."""
    return title_passes(job.get("title")) and location_passes(job.get("location"))
