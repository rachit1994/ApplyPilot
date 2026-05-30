"""Apply quota / cost controls: model defaults, prompt slimming, session reuse."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Literal

from applypilot import config

_SESSION_LOCK = threading.Lock()

# Host markers where CAPTCHA automation instructions are worth the token cost.
CAPTCHA_HOST_MARKERS: tuple[str, ...] = (
    "workday",
    "myworkdayjobs",
    "indeed",
    "glassdoor",
    "taleo",
    "icims",
    "oraclecloud",
    "smartrecruiters",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip()
    return stripped if stripped else default


def apply_model_default(cli_override: str | None = None) -> str:
    """Primary Claude model for apply runs (default haiku)."""
    if cli_override:
        return cli_override.strip()
    return _env_str(
        "APPLYPILOT_APPLY_MODEL",
        str(config.DEFAULTS.get("apply_model_default", "haiku")),
    )


def apply_fallback_model() -> str:
    """Escalation model when the primary apply run fails (default sonnet)."""
    return _env_str(
        "APPLYPILOT_APPLY_FALLBACK_MODEL",
        str(config.DEFAULTS.get("apply_fallback_model", "sonnet")),
    )


def prompt_slim_enabled() -> bool:
    return _env_bool(
        "APPLYPILOT_APPLY_PROMPT_SLIM",
        bool(config.DEFAULTS.get("apply_prompt_slim_enabled", True)),
    )


_PROMPT_MODE_CLI_OVERRIDE: str | None = None


def set_apply_prompt_mode_override(mode: str | None) -> None:
    """CLI --prompt-mode wins over env until cleared."""
    global _PROMPT_MODE_CLI_OVERRIDE
    if mode is None:
        _PROMPT_MODE_CLI_OVERRIDE = None
        return
    normalized = mode.strip().lower()
    if normalized not in ("legacy", "playbook"):
        raise ValueError(f"Invalid apply prompt mode: {mode!r}")
    _PROMPT_MODE_CLI_OVERRIDE = normalized


def apply_prompt_mode() -> Literal["legacy", "playbook"]:
    """Apply stdin prompt: legacy (full agent prompt) or playbook (worker doc only)."""
    if _PROMPT_MODE_CLI_OVERRIDE:
        return _PROMPT_MODE_CLI_OVERRIDE  # type: ignore[return-value]
    raw = _env_str(
        "APPLYPILOT_APPLY_PROMPT_MODE",
        str(config.DEFAULTS.get("apply_prompt_mode", "legacy")),
    ).lower()
    if raw in ("legacy", "playbook"):
        return raw  # type: ignore[return-value]
    return "legacy"


def session_reuse_enabled() -> bool:
    return _env_bool(
        "APPLYPILOT_APPLY_SESSION_REUSE",
        bool(config.DEFAULTS.get("apply_session_reuse_enabled", True)),
    )


def gmail_mcp_enabled() -> bool:
    return _env_bool(
        "APPLYPILOT_APPLY_GMAIL_MCP",
        bool(config.DEFAULTS.get("apply_gmail_mcp_enabled", False)),
    )


def job_likely_needs_captcha(job: dict) -> bool:
    if not prompt_slim_enabled():
        return True
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("application_url", "url", "site", "strategy")
    ).lower()
    return any(marker in blob for marker in CAPTCHA_HOST_MARKERS)


def job_likely_needs_gmail(job: dict) -> bool:
    if gmail_mcp_enabled():
        return True
    if not prompt_slim_enabled():
        return True
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("application_url", "url", "site")
    ).lower()
    if any(
        marker in blob
        for marker in ("greenhouse", "lever.co", "ashby", "workday", "myworkdayjobs")
    ):
        return True
    # LinkedIn rows often hide the ATS host until the agent follows Apply off-site.
    if "linkedin.com" in blob or blob.strip() == "linkedin":
        return True
    return False


def session_store_path(worker_id: int) -> Path:
    config.APPLY_WORKER_DIR.mkdir(parents=True, exist_ok=True)
    return config.APPLY_WORKER_DIR / f"claude-session-w{worker_id}.json"


def load_session_id(worker_id: int) -> str | None:
    path = session_store_path(worker_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    sid = data.get("session_id")
    return str(sid).strip() if sid else None


def save_session_id(worker_id: int, session_id: str) -> None:
    sid = session_id.strip()
    if not sid:
        return
    path = session_store_path(worker_id)
    with _SESSION_LOCK:
        path.write_text(
            json.dumps({"session_id": sid}, indent=2),
            encoding="utf-8",
        )


def clear_session_id(worker_id: int) -> None:
    path = session_store_path(worker_id)
    with _SESSION_LOCK:
        if path.exists():
            path.unlink()


def ensure_session_id(worker_id: int) -> str:
    """Return persisted session id, creating one if session reuse is enabled."""
    existing = load_session_id(worker_id)
    if existing:
        return existing
    sid = str(uuid.uuid4())
    save_session_id(worker_id, sid)
    return sid


def is_stale_session_error(text: str) -> bool:
    """True when Claude CLI cannot resume a persisted session id."""
    lower = text.lower()
    return "no conversation found with session" in lower


def parse_session_id_from_message(msg: dict) -> str | None:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
        value = msg.get(key)
        if value:
            return str(value).strip()
    return None


def should_escalate_to_fallback(
    result: str,
    *,
    primary: str,
    fallback: str,
    is_permanent_failure,
) -> bool:
    """True when we should retry the same job once on the fallback model."""
    if primary == fallback:
        return False
    if result in ("skipped", "applied") or result.startswith("submitted_unverified"):
        return False
    if result in ("expired", "captcha", "login_issue"):
        return False
    if is_permanent_failure(result):
        return False
    reason, _detail = _parse_result_reason(result)
    if reason in ("claude_quota_exhausted", "claude_auth_failed", "claude_stale_session"):
        return False
    if reason in ("inactivity_timeout", "wall_timeout"):
        return False
    return result.startswith("failed:")


def _parse_result_reason(result: str) -> tuple[str, str | None]:
    if not result.startswith("failed:"):
        return result, None
    rest = result[len("failed:") :]
    if ":" in rest:
        reason, detail = rest.split(":", 1)
        return reason, detail
    return rest, None


def apply_telemetry_flags() -> dict[str, bool | str]:
    """Snapshot of quota-related toggles for llm_usage metadata."""
    return {
        "prompt_slim": prompt_slim_enabled(),
        "prompt_mode": apply_prompt_mode(),
        "session_reuse": session_reuse_enabled(),
        "gmail_mcp": gmail_mcp_enabled(),
        "apply_model_default": apply_model_default(),
        "apply_fallback_model": apply_fallback_model(),
    }
