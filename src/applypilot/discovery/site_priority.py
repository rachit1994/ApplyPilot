"""Preferred job boards — discovered and applied before other sources."""

from __future__ import annotations

PRIORITY_SITE_NAMES: tuple[str, ...] = ("Greenhouse", "Lever", "Ashby", "LinkedIn", "Wellfound")

APPLY_QUEUE_ORDER_LABEL = "Greenhouse → Lever → Ashby → LinkedIn → Wellfound → other"


def is_priority_site_name(name: str | None) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith(("greenhouse:", "lever:", "ashby:")):
        return True
    if lowered in {"greenhouse", "lever", "ashby"}:
        return True
    if "greenhouse" in lowered or "lever" in lowered or "ashby" in lowered:
        return True
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
    if lowered.startswith("greenhouse:") or "greenhouse" in lowered:
        return (0, lowered)
    if lowered.startswith("lever:") or "lever" in lowered:
        return (1, lowered)
    if lowered.startswith("ashby:") or "ashby" in lowered:
        return (2, lowered)
    if lowered == "linkedin" or "linkedin" in lowered:
        return (3, lowered)
    if lowered == "wellfound" or "wellfound" in lowered or "angel.co" in lowered:
        return (4, lowered)
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
    """True when job URL/site is an ATS-first or preferred board target."""
    site = (job.get("site") or "").strip().lower()
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("url", "application_url")
    ).lower()
    if site.startswith(("greenhouse:", "lever:", "ashby:")):
        return True
    if any(marker in blob for marker in ("greenhouse.io", "lever.co", "ashbyhq.com")):
        return True
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
