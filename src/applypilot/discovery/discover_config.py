"""User discover.yaml configuration."""

from __future__ import annotations

from typing import Any

import yaml

from applypilot.config import APP_DIR, CONFIG_DIR

_DEFAULT_SOURCES = {
    "jobspy": True,
    "workday": True,
    "smartextract": True,
    "workatastartup": True,
    "hn_hiring": True,
    "himalayas": True,
    "remotive": True,
    "weworkremotely": True,
    "greenhouse": True,
    "lever": True,
    "career_targets": True,
    "funded_startups": False,
}


def load_discover_config() -> dict[str, Any]:
    for path in (APP_DIR / "discover.yaml", CONFIG_DIR / "discover.example.yaml"):
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return _normalize(data)
    return _normalize({})


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    raw_sources = data.get("sources") or {}
    sources = dict(_DEFAULT_SOURCES)
    if isinstance(raw_sources, dict):
        for key, val in raw_sources.items():
            if key in sources:
                sources[key] = bool(val)

    agent = data.get("agent_discover") or {}
    if not isinstance(agent, dict):
        agent = {}

    return {
        "sources": sources,
        "agent_discover": {
            "enabled": bool(agent.get("enabled", True)),
            "max_pages": int(agent.get("max_pages", 3)),
            "headless": bool(agent.get("headless", False)),
        },
        "workatastartup": data.get("workatastartup") or {},
        "hn_hiring": data.get("hn_hiring") or {},
        "himalayas": data.get("himalayas") or {},
        "funded_startups": data.get("funded_startups") or {},
    }
