"""Preferred job boards — discovered and applied before other sources."""

from __future__ import annotations

PRIORITY_SITE_NAMES: tuple[str, ...] = ("LinkedIn", "Wellfound")

APPLY_QUEUE_ORDER_LABEL = "LinkedIn → Wellfound → ATS boards → other"


def is_priority_site_name(name: str | None) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    if lowered in {"linkedin", "linkedin.com", "wellfound"}:
        return True
    if "linkedin" in lowered:
        return True
    if "wellfound" in lowered or "angel.co" in lowered:
        return True
    return any(preferred.lower() == lowered for preferred in PRIORITY_SITE_NAMES)


def site_order_key(name: str) -> tuple[int, str]:
    """Lower sort key = higher priority."""
    lowered = (name or "").strip().lower()
    for idx, preferred in enumerate(PRIORITY_SITE_NAMES):
        if lowered == preferred.lower():
            return (idx, lowered)
    return (len(PRIORITY_SITE_NAMES), lowered)


def prioritize_site_dicts(sites: list[dict]) -> list[dict]:
    return sorted(sites, key=lambda row: site_order_key(str(row.get("name") or "")))


def prioritize_target_dicts(targets: list[dict]) -> list[dict]:
    return sorted(targets, key=lambda row: site_order_key(str(row.get("name") or "")))


def sort_site_count_rows(rows: list[dict]) -> list[dict]:
    """Sort {site, count} rows with priority boards first."""

    def key(row: dict) -> tuple[int, str]:
        site = str(row.get("site") or "")
        return site_order_key(site)

    return sorted(rows, key=key)


def job_is_priority_board(job: dict) -> bool:
    """True when job URL/site is LinkedIn or Wellfound (incl. angel.co legacy URLs)."""
    site = (job.get("site") or "").strip().lower()
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("url", "application_url")
    ).lower()
    if site == "linkedin" or site == "linkedin.com" or "linkedin.com" in blob:
        return True
    if site == "wellfound" or "wellfound.com" in blob or "angel.co" in blob:
        return True
    return is_priority_site_name(job.get("site"))


def filter_priority_site_dicts(sites: list[dict]) -> list[dict]:
    return [row for row in sites if is_priority_site_name(str(row.get("name") or ""))]


def sort_source_count_rows(rows: list[dict]) -> list[dict]:
    """Sort discover rollup rows ({source, ...}) with priority boards first."""

    def key(row: dict) -> tuple[int, str]:
        source = str(row.get("source") or "")
        return site_order_key(source)

    return sorted(rows, key=key)
