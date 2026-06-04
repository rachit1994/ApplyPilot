"""Display labels and SQL filters for jobs scored below 7 (stats + jobs list)."""

from __future__ import annotations

PRE_FILTER_DISPLAY: dict[str, str] = {
    "title:junior_or_intern": "Junior or intern title",
    "title:exec_non_eng": "Executive non-engineering role",
    "title:adjacent_role": "Adjacent non-core role",
    "title:not_in_allowlist": "Title outside target roles",
    "location:reject_pattern": "Location outside target regions",
    "salary:below_floor": "Salary below floor",
    "description:blocked_keyword": "Blocked JD keyword",
    "description:junior_signal": "Junior signal in JD",
    "profile:low_keyword_overlap": "Low profile/JD keyword overlap",
    "embedding_low": "Low resume/JD embedding match",
}

DISPLAY_LABELS: frozenset[str] = frozenset(
    {
        *PRE_FILTER_DISPLAY.values(),
        "Work authorization or visa concern",
        "Compensation concern",
        "Location mismatch",
        "Seniority mismatch",
        "Skill or requirement gaps",
        "Moderate LLM fit",
        "Low LLM fit",
        "Other low-score reason",
    }
)


def display_reason(reason: str | None, reasoning: str | None) -> str:
    raw = (reason or "").strip()
    if raw:
        key = raw.replace("pre_filter:", "")
        return PRE_FILTER_DISPLAY.get(key, key.replace("_", " "))

    text = (reasoning or "").lower()
    if any(k in text for k in ("visa", "sponsor", "authorization", "work authorization")):
        return "Work authorization or visa concern"
    if any(k in text for k in ("salary", "compensation", "pay")):
        return "Compensation concern"
    if any(k in text for k in ("location", "remote", "onsite", "hybrid", "relocat")):
        return "Location mismatch"
    if any(k in text for k in ("junior", "intern", "seniority", "years", "experience level")):
        return "Seniority mismatch"
    if any(k in text for k in ("missing", "gap", "lack", "skills", "requirements", "technologies")):
        return "Skill or requirement gaps"
    if any(k in text for k in ("sales", "customer success", "product manager", "non-engineering")):
        return "Adjacent non-core role"
    if text.startswith("maybe"):
        return "Moderate LLM fit"
    if text.startswith("skip"):
        return "Low LLM fit"
    return "Other low-score reason"


def _pre_filter_empty_sql() -> str:
    return "(pre_filter_reason IS NULL OR TRIM(pre_filter_reason) = '')"


def _reasoning_contains_sql(*keywords: str) -> str:
    parts = [
        f"LOWER(COALESCE(score_reasoning, '')) LIKE '%{k.lower()}%'" for k in keywords
    ]
    return f"({_pre_filter_empty_sql()} AND ({' OR '.join(parts)}))"


def _pre_filter_key_sql(key: str) -> str:
    return (
        f"(TRIM(COALESCE(pre_filter_reason, '')) IN ('{key}', 'pre_filter:{key}'))"
    )


def _match_sql_for_label(label: str) -> str | None:
    if label not in DISPLAY_LABELS:
        return None

    if label == "Other low-score reason":
        parts = [
            p
            for other in DISPLAY_LABELS
            if other != "Other low-score reason"
            for p in [_match_sql_for_label(other)]
            if p
        ]
        if not parts:
            return "1=1"
        return f"NOT ({' OR '.join(parts)})"

    branches: list[str] = []
    for key, display in PRE_FILTER_DISPLAY.items():
        if display == label:
            branches.append(_pre_filter_key_sql(key))

    if label == "Work authorization or visa concern":
        branches.append(
            _reasoning_contains_sql(
                "visa", "sponsor", "authorization", "work authorization"
            )
        )
    elif label == "Compensation concern":
        branches.append(_reasoning_contains_sql("salary", "compensation", "pay"))
    elif label == "Location mismatch":
        branches.append(
            _reasoning_contains_sql("location", "remote", "onsite", "hybrid", "relocat")
        )
    elif label == "Seniority mismatch":
        branches.append(
            _reasoning_contains_sql(
                "junior", "intern", "seniority", "years", "experience level"
            )
        )
    elif label == "Skill or requirement gaps":
        branches.append(
            _reasoning_contains_sql(
                "missing", "gap", "lack", "skills", "requirements", "technologies"
            )
        )
    elif label == "Moderate LLM fit":
        branches.append(
            f"({_pre_filter_empty_sql()} AND LOWER(COALESCE(score_reasoning, '')) "
            "LIKE 'maybe%')"
        )
    elif label == "Low LLM fit":
        branches.append(
            f"({_pre_filter_empty_sql()} AND LOWER(COALESCE(score_reasoning, '')) "
            "LIKE 'skip%')"
        )
    elif label == "Adjacent non-core role":
        branches.append(
            _reasoning_contains_sql(
                "sales", "customer success", "product manager", "non-engineering"
            )
        )

    if label not in PRE_FILTER_DISPLAY.values() and label not in (
        "Work authorization or visa concern",
        "Compensation concern",
        "Location mismatch",
        "Seniority mismatch",
        "Skill or requirement gaps",
        "Moderate LLM fit",
        "Low LLM fit",
    ):
        escaped = label.replace("'", "''")
        branches.append(
            "(TRIM(COALESCE(pre_filter_reason, '')) != '' "
            "AND REPLACE(TRIM(REPLACE(COALESCE(pre_filter_reason, ''), 'pre_filter:', '')), "
            f"'_', ' ') = '{escaped}')"
        )

    if not branches:
        return None
    return f"({' OR '.join(branches)})"


def low_score_reason_filter_clause(display_label: str | None) -> str | None:
    """WHERE fragment (no AND) for jobs matching a Below-7 display label."""
    label = (display_label or "").strip()
    if not label:
        return None
    match = _match_sql_for_label(label)
    if match is None:
        return None
    return f"(fit_score IS NOT NULL AND fit_score < 7 AND ({match}))"
