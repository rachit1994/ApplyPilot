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


def apply_engine(cli_override: str | None = None) -> Literal["claude", "direct"]:
    """Apply execution engine.

    'direct' (default) — deterministic Playwright Direct Apply (~$0 Claude/apply)
                         for Greenhouse/Lever/Ashby; optional Claude rescue tier.
    'claude'           — Claude Code browser agent (~$0.15/apply) for all jobs.
    """
    default = str(config.DEFAULTS.get("apply_engine", "direct")).strip().lower()
    if default not in ("direct", "claude"):
        default = "direct"
    raw = (cli_override or _env_str("APPLYPILOT_APPLY_ENGINE", default)).strip().lower()
    return "direct" if raw == "direct" else "claude"


def direct_gemini_enabled() -> bool:
    """Allow the Resolver Tier-2 (one cheap Gemini call for novel required fields)."""
    return _env_bool("APPLYPILOT_DIRECT_GEMINI", True)


def email_verification_enabled() -> bool:
    """Read employer verification codes from Gmail during Direct Apply."""
    return _env_bool("APPLYPILOT_DIRECT_EMAIL_VERIFY", True)


def captcha_solving_enabled() -> bool:
    """Solve visible reCAPTCHA v2 via CapSolver when CAPSOLVER_API_KEY is set."""
    if not _env_bool("APPLYPILOT_DIRECT_CAPTCHA", True):
        return False
    return bool(os.environ.get("CAPSOLVER_API_KEY", "").strip())


def direct_escalate_to_claude() -> bool:
    """When Direct Apply can't finish a job, fall back to the Claude path.

    Off by default so a cost-capped run never silently spends Claude budget;
    unresolved jobs are parked (failed:direct_*) for a later Claude pass.
    """
    return _env_bool("APPLYPILOT_DIRECT_ESCALATE", False)


def direct_job_timeout() -> float:
    """Hard wall-clock budget (seconds) for one Direct Apply attempt.

    The Driver runs in-process (no subprocess wall-timeout covers it), so a hung
    Playwright call on an unfamiliar form could otherwise stall a worker for the
    whole night. On timeout the job escalates/parks and the worker moves on.
    """
    try:
        return float(_env_str("APPLYPILOT_DIRECT_JOB_TIMEOUT", "100"))
    except ValueError:
        return 100.0


def max_per_ats_family_per_day() -> int:
    """IP-reputation cap: max submits per ATS family per local day (0 = unlimited)."""
    try:
        return int(_env_str("APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY", "75"))
    except ValueError:
        return 75


def max_per_apex_domain_per_day() -> int:
    """IP-reputation cap: max submits per company apex domain per day (0 = unlimited)."""
    try:
        return int(_env_str("APPLYPILOT_MAX_PER_APEX_DOMAIN_PER_DAY", "25"))
    except ValueError:
        return 25


def apply_model_default(cli_override: str | None = None) -> str:
    """Primary Claude model for apply runs (default haiku)."""
    if cli_override:
        return cli_override.strip()
    return _env_str(
        "APPLYPILOT_APPLY_MODEL",
        str(config.DEFAULTS.get("apply_model_default", "haiku")),
    )


def apply_retry_cooldown_hours() -> float:
    """Hours a failed job is parked (apply_not_before) before it can be re-acquired.

    Keeps a continuous/overnight run from re-applying to the same jobs in a tight
    loop: each non-permanent failure waits out the cooldown before the next try.
    """
    try:
        return float(
            _env_str(
                "APPLYPILOT_APPLY_RETRY_COOLDOWN_HOURS",
                str(config.DEFAULTS.get("apply_retry_cooldown_hours", 18)),
            )
        )
    except ValueError:
        return float(config.DEFAULTS.get("apply_retry_cooldown_hours", 18))


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
_DETERMINISTIC_ONLY_CLI_OVERRIDE: bool | None = None


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


def require_gmail_confirmation() -> bool:
    return _env_bool(
        "APPLYPILOT_APPLY_REQUIRE_GMAIL_CONFIRMATION",
        bool(config.DEFAULTS.get("apply_require_gmail_confirmation", True)),
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


def _apply_profile_section(profile: dict | None = None) -> dict:
    if profile is None:
        try:
            profile = config.load_profile()
        except FileNotFoundError:
            profile = {}
    section = profile.get("apply")
    return section if isinstance(section, dict) else {}


def _optional_positive_int(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _optional_positive_float(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def apply_claude_max_per_run(profile: dict | None = None) -> int | None:
    """Max Claude apply subprocesses per run (None = unlimited)."""
    section = _apply_profile_section(profile)
    for key in ("claude_max_per_run", "apply_claude_max_per_run"):
        if key in section:
            cap = _optional_positive_int(section.get(key))
            if cap is not None:
                return cap
    env_cap = _optional_positive_int(os.environ.get("APPLYPILOT_APPLY_CLAUDE_MAX_PER_RUN"))
    if env_cap is not None:
        return env_cap
    return _optional_positive_int(config.DEFAULTS.get("apply_claude_max_per_run"))


def apply_claude_max_cost_usd_per_run(profile: dict | None = None) -> float | None:
    """Max Claude apply spend (USD) per run (None = unlimited)."""
    section = _apply_profile_section(profile)
    for key in ("claude_max_cost_usd_per_run", "apply_claude_max_cost_usd_per_run"):
        if key in section:
            cap = _optional_positive_float(section.get(key))
            if cap is not None:
                return cap
    env_cap = _optional_positive_float(
        os.environ.get("APPLYPILOT_APPLY_CLAUDE_MAX_COST_USD_PER_RUN")
    )
    if env_cap is not None:
        return env_cap
    return _optional_positive_float(config.DEFAULTS.get("apply_claude_max_cost_usd_per_run"))


def set_deterministic_only_override(enabled: bool | None) -> None:
    """CLI --deterministic-only wins until cleared."""
    global _DETERMINISTIC_ONLY_CLI_OVERRIDE
    _DETERMINISTIC_ONLY_CLI_OVERRIDE = enabled


def deterministic_only_enabled() -> bool:
    if _DETERMINISTIC_ONLY_CLI_OVERRIDE is not None:
        return _DETERMINISTIC_ONLY_CLI_OVERRIDE
    return _env_bool("APPLYPILOT_APPLY_DETERMINISTIC_ONLY", False)


_SKIP_ATS_FAMILIES_DEFAULT = ""


def skipped_ats_families() -> frozenset[str]:
    """ATS families to skip for discover sources and direct apply dispatch.

    Defaults to no skipped families. Override with APPLYPILOT_SKIP_ATS_FAMILIES
    (comma-separated) when a specific ATS adapter should be temporarily parked.
    """
    raw = os.environ.get("APPLYPILOT_SKIP_ATS_FAMILIES")
    if raw is None:
        raw = _SKIP_ATS_FAMILIES_DEFAULT
    raw = raw.strip()
    if not raw or raw.lower() in ("0", "false", "none", "off"):
        return frozenset()
    return frozenset(
        part.strip().lower()
        for part in raw.split(",")
        if part.strip()
    )


def direct_excluded_families() -> frozenset[str]:
    """Families the deterministic driver must not dispatch (alias of skipped_ats_families)."""
    return skipped_ats_families()


def discover_excluded_sources() -> frozenset[str]:
    """Discover source keys to disable (same names as ATS families where applicable)."""
    return skipped_ats_families()


def apply_telemetry_flags() -> dict[str, bool | str]:
    """Snapshot of quota-related toggles for llm_usage metadata."""
    return {
        "prompt_slim": prompt_slim_enabled(),
        "prompt_mode": apply_prompt_mode(),
        "session_reuse": session_reuse_enabled(),
        "gmail_mcp": gmail_mcp_enabled(),
        "require_gmail_confirmation": require_gmail_confirmation(),
        "apply_model_default": apply_model_default(),
        "apply_fallback_model": apply_fallback_model(),
        "deterministic_only": deterministic_only_enabled(),
        "claude_max_per_run": apply_claude_max_per_run(),
        "claude_max_cost_usd_per_run": apply_claude_max_cost_usd_per_run(),
    }
