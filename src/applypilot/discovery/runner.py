"""Unified discover runner — all sources behind one entry point."""

from __future__ import annotations

import logging
import os
from typing import Any

from applypilot.database import get_connection, record_discover_source_stats
from applypilot.discovery.career_targets import load_career_targets, partition_career_targets
from applypilot.discovery.discover_config import load_discover_config
from applypilot.discovery.site_priority import filter_priority_site_dicts
from applypilot.discovery.smartextract import (
    load_sites,
    partition_sites_by_mode,
    run_smart_extract,
)
from applypilot.apply.eligibility import priority_boards_only_enabled

log = logging.getLogger(__name__)


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return 0


def _source_counts(outcome: dict[str, Any]) -> tuple[int, int]:
    result = outcome.get("result")
    if not isinstance(result, dict):
        return 0, 0
    discovered = _first_int(
        result,
        ("total", "found", "fetched", "listed", "jobs_found", "processed", "total_targets"),
    )
    new = _first_int(result, ("new", "inserted", "added", "jobs_new"))
    existing = _first_int(result, ("existing", "duplicate", "duplicates", "updated"))
    passed_filter = _first_int(result, ("passed", "kept", "stored", "saved"))
    if passed_filter == 0:
        passed_filter = new + existing
    if discovered == 0:
        discovered = max(passed_filter, new + existing)
    return discovered, passed_filter


def _emit_source_progress(
    source: str,
    outcome: dict[str, Any],
    *,
    index: int,
    total: int,
) -> None:
    run_id = os.environ.get("APPLYPILOT_RUN_ID", "").strip()
    if not run_id:
        return
    from applypilot.orchestration.events import emit_run_event

    status = str(outcome.get("status", "?"))
    result = outcome.get("result")
    new_jobs = 0
    if isinstance(result, dict):
        for key in ("new", "inserted", "added", "jobs_new"):
            if key in result and isinstance(result[key], int):
                new_jobs = int(result[key])
                break
    emit_run_event(
        "source_progress",
        stage="discover",
        run_id=run_id,
        message=f"{source}: {status}",
        payload={
            "source": source,
            "status": status,
            "new_jobs": new_jobs,
            "index": index,
            "total": total,
            "detail": f"{source} — {status}",
        },
    )


def _record_source_stats(source: str, outcome: dict[str, Any]) -> None:
    status = str(outcome.get("status", ""))
    if status.startswith("error"):
        return
    discovered, passed_filter = _source_counts(outcome)
    record_discover_source_stats(
        get_connection(),
        source=source,
        run_id=os.environ.get("APPLYPILOT_RUN_ID", "").strip(),
        discovered=discovered,
        passed_filter=passed_filter,
    )


def _run_source(name: str, fn, *args, **kwargs) -> dict[str, Any]:
    try:
        result = fn(*args, **kwargs)
        return {"status": "ok", "result": result}
    except Exception as exc:
        log.exception("%s discover failed", name)
        return {"status": f"error: {exc}", "result": None}


def run_discover(*, workers: int = 1) -> dict[str, Any]:
    """Run all enabled discover sources. Returns per-source stats."""
    cfg = load_discover_config()
    sources = cfg["sources"]
    agent_cfg = cfg["agent_discover"]
    if priority_boards_only_enabled():
        sources = {key: False for key in sources}
        sources["greenhouse"] = True
        sources["lever"] = True
        sources["ashby"] = True
        sources["smartextract"] = True
        agent_cfg = {**agent_cfg, "enabled": False}
        log.info("Discover sources limited to ATS APIs plus priority SmartExtract boards")
    stats: dict[str, Any] = {}

    # Public ATS APIs produce direct, deterministic application URLs. Run them
    # before broad scrape sources so the apply queue has high-confidence rows
    # as early as possible.
    if sources.get("greenhouse"):
        from applypilot.discovery.ats.greenhouse import run_greenhouse_discovery

        stats["greenhouse"] = _run_source("greenhouse", run_greenhouse_discovery)

    if sources.get("lever"):
        from applypilot.discovery.ats.lever import run_lever_discovery

        stats["lever"] = _run_source("lever", run_lever_discovery)

    if sources.get("ashby"):
        from applypilot.discovery.ats.ashby import run_ashby_discovery

        stats["ashby"] = _run_source("ashby", run_ashby_discovery)

    if sources.get("jobspy"):
        from applypilot.discovery.jobspy import run_discovery

        stats["jobspy"] = _run_source("jobspy", run_discovery)

    if sources.get("workday"):
        from applypilot.discovery.workday import run_workday_discovery

        stats["workday"] = _run_source("workday", run_workday_discovery, workers=workers)

    if sources.get("remoteok"):
        from applypilot.discovery.feeds.remoteok import run_remoteok_discovery

        tags = (cfg.get("remoteok") or {}).get("tags", "dev")
        stats["remoteok"] = _run_source("remoteok", run_remoteok_discovery, tags=tags)

    if sources.get("remotive"):
        from applypilot.discovery.feeds.remotive import run_remotive_discovery

        stats["remotive"] = _run_source("remotive", run_remotive_discovery)

    if sources.get("himalayas"):
        from applypilot.discovery.feeds.himalayas import run_himalayas_discovery

        limit = int((cfg.get("himalayas") or {}).get("limit", 50))
        stats["himalayas"] = _run_source("himalayas", run_himalayas_discovery, limit=limit)

    if sources.get("weworkremotely"):
        from applypilot.discovery.feeds.wwr import run_wwr_discovery

        stats["weworkremotely"] = _run_source("weworkremotely", run_wwr_discovery)

    if sources.get("hn_hiring"):
        from applypilot.discovery.hn_hiring import run_hn_hiring_discovery

        url = (cfg.get("hn_hiring") or {}).get("url", "https://hnhiring.com/locations/remote")
        stats["hn_hiring"] = _run_source("hn_hiring", run_hn_hiring_discovery, url=url)

    if sources.get("workatastartup"):
        from applypilot.discovery.workatastartup import (
            build_waas_listing_variants,
            run_workatastartup_discovery,
        )

        waas_cfg = cfg.get("workatastartup") or {}
        stats["workatastartup"] = _run_source(
            "workatastartup",
            run_workatastartup_discovery,
            build_waas_listing_variants(),
            headless=bool(waas_cfg.get("headless", True)),
            use_chrome_session=bool(waas_cfg.get("use_chrome_session", False)),
        )

    yaml_sites = load_sites()
    if priority_boards_only_enabled():
        yaml_sites = filter_priority_site_dicts(yaml_sites)
        log.info("Discover limited to priority boards: LinkedIn, Wellfound")
    yaml_agent, yaml_smart = partition_sites_by_mode(yaml_sites)
    extra_smart_sites: list[dict] = list(yaml_smart)
    agent_sites: list[dict] = list(yaml_agent)

    if sources.get("career_targets"):
        _skipped, agent_sites, extra_smart = partition_career_targets(load_career_targets())
        extra_smart_sites.extend(extra_smart)
        stats["career_targets"] = {
            "status": "ok",
            "result": {
                "total_targets": len(load_career_targets()),
                "workday_handled_separately": len(_skipped),
                "agent_sites": len(agent_sites),
                "smartextract_sites": len(extra_smart),
            },
        }

    if sources.get("funded_startups"):
        from applypilot.discovery.funded_startups import build_funded_startup_sites

        funded_sites = build_funded_startup_sites(cfg.get("funded_startups") or {})
        extra_smart_sites.extend(funded_sites)
        stats["funded_startups"] = {
            "status": "ok",
            "result": {
                "smartextract_sites": len(funded_sites),
                "source": "yc_community_dataset",
            },
        }

    if agent_cfg.get("enabled") and agent_sites:
        from applypilot.discovery.agent_browse import run_agent_sites

        stats["agent_discover"] = _run_source(
            "agent_discover",
            run_agent_sites,
            agent_sites,
            max_pages=agent_cfg.get("max_pages", 3),
            headless=agent_cfg.get("headless", False),
        )

    if sources.get("smartextract"):
        merged_sites = extra_smart_sites
        stats["smartextract"] = _run_source(
            "smartextract",
            run_smart_extract,
            sites=merged_sites,
            workers=workers,
            agent_fallback_enabled=agent_cfg.get("enabled", True),
            agent_max_pages=agent_cfg.get("max_pages", 3),
            agent_headless=agent_cfg.get("headless", False),
        )

    total_sources = len(stats)
    for index, (name, outcome) in enumerate(stats.items()):
        if isinstance(outcome, dict):
            _record_source_stats(name, outcome)
            _emit_source_progress(name, outcome, index=index, total=total_sources)

    return stats
