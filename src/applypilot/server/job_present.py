"""Normalize job rows for dashboard API responses."""

from __future__ import annotations

import re
from typing import Any

_TEXT_FIELDS = (
    "title",
    "site",
    "location",
    "salary",
    "strategy",
    "score_reasoning",
    "pre_filter_reason",
    "apply_status",
    "apply_error",
    "detail_error",
    "application_url",
)


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def infer_remote_policy(location: str | None) -> str | None:
    if not location or not str(location).strip():
        return None
    loc = str(location).lower()
    has_remote = "remote" in loc
    has_hybrid = "hybrid" in loc
    has_onsite = any(
        token in loc
        for token in ("onsite", "on-site", "on site", "in-office", "in office", "office-based")
    )
    if has_remote and has_hybrid:
        return "Hybrid"
    if has_remote and has_onsite:
        return "Mixed"
    if has_remote:
        return "Remote"
    if has_hybrid:
        return "Hybrid"
    if has_onsite:
        return "On-site"
    return "On-site"


def present_job_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce job row dict for JobRow: trim blanks, add derived remote."""
    job = dict(row)
    for key in _TEXT_FIELDS:
        if key in job:
            job[key] = _blank_to_none(job.get(key))
    job["remote"] = infer_remote_policy(job.get("location"))
    return job
