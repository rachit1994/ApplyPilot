"""Load employer career-page targets and map them to discover strategies."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from applypilot.config import APP_DIR, CONFIG_DIR

log = logging.getLogger(__name__)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_workday_employer_keys() -> set[str]:
    """Keys under employers.yaml `employers` map."""
    data = _load_yaml(CONFIG_DIR / "employers.yaml")
    employers = data.get("employers") or {}
    return set(employers.keys()) if isinstance(employers, dict) else set()


def load_career_targets() -> list[dict[str, Any]]:
    """Merge package career_targets.yaml with optional user override."""
    merged: list[dict] = []
    seen: set[str] = set()

    for path in (CONFIG_DIR / "career_targets.yaml", APP_DIR / "career_targets.yaml"):
        data = _load_yaml(path)
        for row in data.get("targets") or []:
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            url = (row.get("careers_url") or row.get("url") or "").strip()
            if not name or not url:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "name": name,
                    "careers_url": url,
                    "mode": (row.get("mode") or "smartextract").strip().lower(),
                    "ats": (row.get("ats") or "custom").strip().lower(),
                    "workday_key": (row.get("workday_key") or "").strip() or None,
                    "greenhouse_board": (row.get("greenhouse_board") or "").strip() or None,
                    "lever_site": (row.get("lever_site") or "").strip() or None,
                    "country_focus": row.get("country_focus") or [],
                }
            )

    return merged


def partition_career_targets(
    targets: list[dict[str, Any]] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split targets into (workday_skip, agent_sites, smartextract_sites)."""
    if targets is None:
        targets = load_career_targets()
    workday_keys = load_workday_employer_keys()
    agent_sites: list[dict] = []
    smart_sites: list[dict] = []
    skipped_workday: list[dict] = []

    for row in targets:
        wd_key = row.get("workday_key")
        if row.get("ats") == "workday" and wd_key and wd_key in workday_keys:
            skipped_workday.append(row)
            continue
        site = {
            "name": row["name"],
            "url": row["careers_url"],
            "type": "static",
            "mode": row.get("mode", "smartextract"),
            "source": "career_targets",
        }
        for key in ("company_priority", "company_priority_reasons"):
            if key in row:
                site[key] = row[key]
        if row.get("mode") == "agent":
            agent_sites.append(site)
        else:
            smart_sites.append(site)

    return skipped_workday, agent_sites, smart_sites
