"""Inbox job-reply configuration (~/.applypilot/inbox.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from applypilot.config import APP_DIR, CONFIG_DIR, load_env

INBOX_CONFIG_PATH = APP_DIR / "inbox.yaml"
INBOX_EXAMPLE_PATH = CONFIG_DIR / "inbox.example.yaml"
V1_INBOX_FOLDER = "other"

DEFAULT_FIXED_REPLY = (
    "Hi. I am actively exploring senior engineering roles and would appreciate "
    "hearing if you are hiring or can point me to the right person on your team."
)


@dataclass(frozen=True)
class InboxSettings:
    enabled: bool
    inbox_folder: str
    since_days: int
    scan_limit: int
    classify_limit: int
    max_sends_per_run: int
    job_confidence_threshold: float
    fixed_reply_message: str
    openoutreach_base_url: str
    openoutreach_api_key: str
    openoutreach_campaign: str | None
    require_gemini: bool
    require_unanswered_inbound: bool
    sync_scroll_passes: int
    sync_max_pages: int
    require_approval_for_send: bool


def load_inbox_config() -> InboxSettings:
    load_env()
    import yaml

    data: dict = {}
    if INBOX_CONFIG_PATH.exists():
        data = yaml.safe_load(INBOX_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    elif INBOX_EXAMPLE_PATH.exists():
        data = yaml.safe_load(INBOX_EXAMPLE_PATH.read_text(encoding="utf-8")) or {}

    folder = str(data.get("inbox_folder", V1_INBOX_FOLDER)).lower().strip()
    if folder != V1_INBOX_FOLDER:
        raise ValueError(f"inbox_folder must be '{V1_INBOX_FOLDER}' in v1 (got {folder!r})")

    base_url = os.environ.get(
        "OPENOUTREACH_BASE_URL",
        data.get("openoutreach_base_url", "http://127.0.0.1:8741/v1"),
    ).rstrip("/")
    api_key = os.environ.get("OPENOUTREACH_API_KEY", data.get("openoutreach_api_key", ""))
    campaign = os.environ.get("OPENOUTREACH_INBOX_CAMPAIGN") or os.environ.get(
        "OPENOUTREACH_CAMPAIGN"
    ) or data.get("openoutreach_campaign")

    return InboxSettings(
        enabled=bool(data.get("enabled", False)),
        inbox_folder=folder,
        since_days=int(data.get("since_days", 14)),
        scan_limit=int(data.get("scan_limit", 50)),
        classify_limit=int(data.get("classify_limit", 50)),
        max_sends_per_run=int(data.get("max_sends_per_run", 50)),
        job_confidence_threshold=float(data.get("job_confidence_threshold", 0.7)),
        fixed_reply_message=str(data.get("fixed_reply_message", DEFAULT_FIXED_REPLY)).strip(),
        openoutreach_base_url=base_url,
        openoutreach_api_key=api_key or "",
        openoutreach_campaign=campaign,
        require_gemini=bool(data.get("require_gemini", True)),
        require_unanswered_inbound=bool(data.get("require_unanswered_inbound", True)),
        sync_scroll_passes=int(data.get("sync_scroll_passes", 8)),
        sync_max_pages=int(data.get("sync_max_pages", 20)),
        require_approval_for_send=bool(data.get("require_approval_for_send", True)),
    )


def inbox_is_configured(settings: InboxSettings | None = None) -> bool:
    cfg = settings or load_inbox_config()
    return cfg.enabled and bool(cfg.openoutreach_api_key)
