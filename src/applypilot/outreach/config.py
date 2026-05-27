"""Outreach and OpenOutreach configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from applypilot.config import APP_DIR, CONFIG_DIR, DEFAULTS, load_env

OUTREACH_CONFIG_PATH = APP_DIR / "outreach.yaml"
OUTREACH_EXAMPLE_PATH = CONFIG_DIR / "outreach.example.yaml"


@dataclass(frozen=True)
class OutreachSettings:
    enabled: bool
    min_fit_score: int
    max_job_age_hours: int
    weekly_connect_target: int
    max_connects_per_run: int
    max_messages_per_run: int
    poll_connected_every_minutes: int
    skip_if_applied: bool
    require_applied_before_send: bool
    referral_message_template: str
    openoutreach_base_url: str
    openoutreach_api_key: str
    openoutreach_campaign: str | None
    require_gemini_for_draft: bool
    ensure_tailored_resume: bool
    tailor_validation_mode: str
    resume_excerpt_chars: int
    referral_message_max_words: int


def _default_outreach_dict() -> dict:
    if OUTREACH_EXAMPLE_PATH.exists():
        import yaml

        return yaml.safe_load(OUTREACH_EXAMPLE_PATH.read_text(encoding="utf-8")) or {}
    return {}


def load_outreach_config() -> OutreachSettings:
    """Load outreach.yaml merged with environment overrides."""
    load_env()
    import yaml

    data: dict = {}
    if OUTREACH_CONFIG_PATH.exists():
        data = yaml.safe_load(OUTREACH_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    elif OUTREACH_EXAMPLE_PATH.exists():
        data = _default_outreach_dict()

    base_url = os.environ.get(
        "OPENOUTREACH_BASE_URL",
        data.get("openoutreach_base_url", "http://127.0.0.1:8741/v1"),
    ).rstrip("/")
    api_key = os.environ.get("OPENOUTREACH_API_KEY", data.get("openoutreach_api_key", ""))
    campaign = os.environ.get("OPENOUTREACH_CAMPAIGN") or data.get("openoutreach_campaign")

    return OutreachSettings(
        enabled=bool(data.get("enabled", False)),
        min_fit_score=int(data.get("min_fit_score", DEFAULTS["min_score"])),
        max_job_age_hours=int(data.get("max_job_age_hours", 72)),
        weekly_connect_target=int(data.get("weekly_connect_target", 12)),
        max_connects_per_run=int(data.get("max_connects_per_run", 5)),
        max_messages_per_run=int(data.get("max_messages_per_run", 10)),
        poll_connected_every_minutes=int(data.get("poll_connected_every_minutes", 60)),
        skip_if_applied=bool(data.get("skip_if_applied", False)),
        require_applied_before_send=bool(data.get("require_applied_before_send", True)),
        referral_message_template=str(data.get("referral_message_template", "") or "").strip(),
        openoutreach_base_url=base_url,
        openoutreach_api_key=api_key or "",
        openoutreach_campaign=campaign,
        require_gemini_for_draft=bool(data.get("require_gemini_for_draft", True)),
        ensure_tailored_resume=bool(data.get("ensure_tailored_resume", True)),
        tailor_validation_mode=str(data.get("tailor_validation_mode", "normal")),
        resume_excerpt_chars=int(data.get("resume_excerpt_chars", 2500)),
        referral_message_max_words=int(data.get("referral_message_max_words", 130)),
    )


def outreach_is_configured(settings: OutreachSettings | None = None) -> bool:
    cfg = settings or load_outreach_config()
    return cfg.enabled and bool(cfg.openoutreach_api_key)
