"""Dashboard-editable settings persisted under ~/.applypilot/dashboard_settings.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from applypilot import config

SETTINGS_PATH = config.APP_DIR / "dashboard_settings.json"

_AGENT_DEFAULTS: dict[str, Any] = {
    "auto_apply_enabled": True,
    # UI default 7 — jobs below this stay out of the auto-apply queue when > 0.
    "apply_min_score": 7.0,
    "tailor_per_job": True,
    "cover_letter": True,
    "cross_source_dedup": True,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_agent(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(_AGENT_DEFAULTS)
    if not isinstance(raw, dict):
        return data
    if "auto_apply_enabled" in raw:
        data["auto_apply_enabled"] = bool(raw["auto_apply_enabled"])
    if "tailor_per_job" in raw:
        data["tailor_per_job"] = bool(raw["tailor_per_job"])
    if "cover_letter" in raw:
        data["cover_letter"] = bool(raw["cover_letter"])
    if "cross_source_dedup" in raw:
        data["cross_source_dedup"] = bool(raw["cross_source_dedup"])
    if "apply_min_score" in raw:
        try:
            score = float(raw["apply_min_score"])
        except (TypeError, ValueError):
            score = float(_AGENT_DEFAULTS["apply_min_score"])
        data["apply_min_score"] = max(0.0, min(10.0, score))
    return data


def _read_file() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_dashboard_settings() -> dict[str, Any]:
    """Return merged dashboard settings (agent section normalized)."""
    payload = _read_file()
    agent = _normalize_agent(payload.get("agent"))
    return {
        "agent": agent,
        "updated_at": payload.get("updated_at"),
    }


def load_agent_settings() -> dict[str, Any]:
    return load_dashboard_settings()["agent"]


def apply_agent_settings_to_config(agent: dict[str, Any] | None = None) -> dict[str, Any]:
    """Push agent settings into in-process config.DEFAULTS for apply queue filtering."""
    normalized = _normalize_agent(agent or load_agent_settings())
    score = float(normalized["apply_min_score"])
    int_score = max(0, min(10, int(round(score))))
    config.DEFAULTS["apply_min_score"] = int_score
    config.DEFAULTS["min_score"] = int_score
    return normalized


def save_agent_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge patch into agent settings, persist, and update config.DEFAULTS."""
    current = load_dashboard_settings()
    merged_agent = _normalize_agent({**current["agent"], **patch})
    payload = {
        "agent": merged_agent,
        "updated_at": _utc_now_iso(),
    }
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    apply_agent_settings_to_config(merged_agent)
    return payload


def bootstrap_dashboard_settings() -> None:
    """Load persisted settings into config at process startup."""
    apply_agent_settings_to_config()
