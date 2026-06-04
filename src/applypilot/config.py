"""ApplyPilot configuration: paths, platform detection, user data."""

import os
import platform
import shutil
from pathlib import Path

# User data directory — all user-specific files live here
APP_DIR = Path(os.environ.get("APPLYPILOT_DIR", Path.home() / ".applypilot"))

# Core paths
DB_PATH = APP_DIR / "applypilot.db"
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_PATH = APP_DIR / "resume.txt"
RESUME_PDF_PATH = APP_DIR / "resume.pdf"
SEARCH_CONFIG_PATH = APP_DIR / "searches.yaml"
ENV_PATH = APP_DIR / ".env"
ROLE_RESUME_DIR = Path(
    os.environ.get(
        "APPLYPILOT_ROLE_RESUME_DIR",
        Path(__file__).resolve().parents[2] / "role_resumes",
    )
)

# Generated output
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
TEMPLATES_DIR = APP_DIR / "templates"
LOG_DIR = APP_DIR / "logs"
RUN_LOG_DIR = LOG_DIR / "runs"

# Chrome worker isolation
CHROME_WORKER_DIR = APP_DIR / "chrome-workers"
APPLY_WORKER_DIR = APP_DIR / "apply-workers"

# Package-shipped config (YAML registries)
PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"


def get_chrome_path() -> str:
    """Auto-detect Chrome/Chromium executable path, cross-platform.

    Override with CHROME_PATH environment variable.
    """
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    system = platform.system()

    if system == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:  # Linux
        candidates = []
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for c in candidates:
        if c and c.exists():
            return str(c)

    # Fall back to PATH search
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "Chrome/Chromium not found. Install Chrome or set CHROME_PATH environment variable."
    )


def get_chrome_user_data() -> Path:
    """Default Chrome user data directory, cross-platform."""
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        return Path.home() / ".config" / "google-chrome"


def templates_dir() -> Path:
    """User template store (~/.applypilot/templates); creates resumes/ and cover_letters/."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    (TEMPLATES_DIR / "resumes").mkdir(parents=True, exist_ok=True)
    (TEMPLATES_DIR / "cover_letters").mkdir(parents=True, exist_ok=True)
    return TEMPLATES_DIR


def load_tailor_a_grade_config(profile: dict) -> dict:
    """A-grade tailoring thresholds from profile['tailor']['a_grade']."""
    tailor = profile.get("tailor") or {}
    a_grade = tailor.get("a_grade") or {}
    companies = a_grade.get("target_companies") or []
    return {
        "min_score": int(a_grade.get("min_score", 9)),
        "target_companies": {
            str(c).strip().lower() for c in companies if str(c).strip()
        },
    }


def ensure_dirs():
    """Create all required directories."""
    for d in [
        APP_DIR,
        TAILORED_DIR,
        COVER_LETTER_DIR,
        LOG_DIR,
        RUN_LOG_DIR,
        CHROME_WORKER_DIR,
        APPLY_WORKER_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)
    templates_dir()


def load_profile() -> dict:
    """Load user profile from ~/.applypilot/profile.json."""
    import json
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Profile not found at {PROFILE_PATH}. Run `applypilot init` first."
        )
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def get_target_roles(profile: dict | None = None) -> list[str]:
    """Roles the candidate is actively pursuing (from profile)."""
    profile = profile or load_profile()
    exp = profile.get("experience", {})
    roles = exp.get("target_roles")
    if isinstance(roles, list) and roles:
        return [str(r).strip() for r in roles if str(r).strip()]
    primary = exp.get("target_role") or profile.get("personal", {}).get(
        "current_job_title", "software engineer"
    )
    return [str(primary).strip()] if primary else ["software engineer"]


def _norm_search_query(text: str | None) -> str:
    import re

    return re.sub(r"[^a-z0-9+#.]+", " ", (text or "").lower()).strip()


def _merge_role_catalog_into_search_config(cfg: dict) -> dict:
    """Append ROLE_CATALOG discover queries and default title allowlist when enabled."""
    if cfg.get("role_catalog_queries") is False:
        return cfg
    try:
        from applypilot.role_resumes import (
            discovery_search_query_entries,
            discovery_title_include_keywords,
        )
    except Exception:
        return cfg

    profile: dict | None = None
    try:
        profile = load_profile()
    except FileNotFoundError:
        profile = None

    existing = {
        _norm_search_query(str(q.get("query")))
        for q in (cfg.get("queries") or [])
        if q.get("query")
    }
    merged_queries = list(cfg.get("queries") or [])
    for entry in discovery_search_query_entries(profile):
        key = _norm_search_query(str(entry.get("query")))
        if key and key not in existing:
            merged_queries.append(entry)
            existing.add(key)
    cfg["queries"] = merged_queries

    if not cfg.get("include_titles"):
        auto_titles = discovery_title_include_keywords()
        if auto_titles:
            cfg["include_titles"] = auto_titles

    return cfg


def load_search_config() -> dict:
    """Load search configuration from ~/.applypilot/searches.yaml."""
    import yaml
    if not SEARCH_CONFIG_PATH.exists():
        # Fall back to package-shipped example
        example = CONFIG_DIR / "searches.example.yaml"
        if example.exists():
            cfg = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
        else:
            cfg = {}
    else:
        cfg = yaml.safe_load(SEARCH_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return _merge_role_catalog_into_search_config(cfg)


def load_location_filter_patterns(
    search_cfg: dict | None = None,
) -> tuple[list[str], list[str]]:
    """Location accept/reject lists from nested location.* or legacy flat keys."""
    cfg = search_cfg if search_cfg is not None else load_search_config()
    loc = cfg.get("location") or {}
    accept = loc.get("accept_patterns") or cfg.get("location_accept") or []
    reject = loc.get("reject_patterns") or cfg.get("location_reject_non_remote") or []
    return [str(x) for x in accept if x], [str(x) for x in reject if x]


def load_sites_config() -> dict:
    """Load sites.yaml configuration (sites list, manual_ats, blocked, etc.)."""
    import yaml
    path = CONFIG_DIR / "sites.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_manual_ats(url: str | None) -> bool:
    """Check if a URL routes through an ATS that requires manual application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("manual_ats", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def is_contractor_marketplace(url: str | None) -> bool:
    """Check if a URL is a contractor/talent marketplace, not a job application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("contractor_marketplaces", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def load_blocked_sites() -> tuple[set[str], list[str]]:
    """Load blocked sites and URL patterns from sites.yaml.

    Returns:
        (blocked_site_names, blocked_url_patterns)
    """
    cfg = load_sites_config()
    blocked = cfg.get("blocked", {})
    sites = set(blocked.get("sites", []))
    patterns = blocked.get("url_patterns", [])
    return sites, patterns


def load_blocked_sso() -> list[str]:
    """Load blocked SSO domains from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("blocked_sso", [])


def load_base_urls() -> dict[str, str | None]:
    """Load site base URLs for URL resolution from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("base_urls", {})


# ---------------------------------------------------------------------------
# Default values — referenced across modules instead of magic numbers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "min_score": 7,
    "apply_min_score": 0,
    "apply_min_experience_years": 5,
    "apply_queue_mode": "all_tailored",
    "max_apply_attempts": 3,
    # Cooldown (hours) before a failed job can be re-acquired. Prevents a
    # continuous/overnight run from re-applying to the same jobs in a tight loop.
    "apply_retry_cooldown_hours": 18,
    "max_tailor_attempts": 5,
    "poll_interval": 60,
    "apply_timeout": 600,
    "apply_inactivity_timeout": 120,
    "apply_quota_pause": 1800,
    "viewport": "1280x900",
    # Apply quota quick-wins (override via APPLYPILOT_APPLY_* env vars)
    "apply_model_default": "haiku",
    "apply_fallback_model": "sonnet",
    "apply_prompt_slim_enabled": True,
    "apply_session_reuse_enabled": True,
    "apply_gmail_mcp_enabled": False,
    "apply_require_gmail_confirmation": True,
    "apply_prompt_mode": "legacy",
    "role_resume_apply_min_score": 7,
    # Apply uses a matched role_resumes PDF when JD alignment score is at least this (1–10).
    "role_resume_jd_min_score": 7,
    # Manifest title/JD score (alias=8, keyword=1 each) required to pick a role resume.
    "role_resume_min_match_score": 3,
    # Target depth for the apply queue (role resume or per-job tailored + apply URL).
    "apply_queue_min_ready": 300,
    # Cover stage: jobs processed per batch (pipeline loops until queue empty).
    "cover_letter_batch_limit": 300,
    # Default apply subprocess engine when APPLYPILOT_APPLY_ENGINE is unset.
    "apply_engine": "direct",
}


def load_env():
    """Load environment variables from ~/.applypilot/.env if it exists."""
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        # Optional dependency (tests and minimal installs should still work).
        return
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    # Also try CWD .env as fallback
    load_dotenv()


# ---------------------------------------------------------------------------
# Tier system — feature gating by installed dependencies
# ---------------------------------------------------------------------------

TIER_LABELS = {
    1: "Discovery",
    2: "AI Scoring & Tailoring",
    3: "Full Auto-Apply",
}

TIER_COMMANDS: dict[int, list[str]] = {
    1: ["init", "run discover", "run enrich", "status", "dashboard"],
    2: ["run score", "run tailor", "run cover", "run pdf", "run"],
    3: ["apply"],
}


def get_tier() -> int:
    """Detect the current tier based on available dependencies.

    Tier 1 (Discovery):            Python + pip
    Tier 2 (AI Scoring & Tailoring): + LLM API key
    Tier 3 (Full Auto-Apply):       + Claude Code CLI + Chrome
    """
    load_env()

    has_llm = any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL"))
    if not has_llm:
        return 1

    has_claude = shutil.which("claude") is not None
    try:
        get_chrome_path()
        has_chrome = True
    except FileNotFoundError:
        has_chrome = False

    if has_claude and has_chrome:
        return 3

    return 2


def check_tier(required: int, feature: str) -> None:
    """Raise SystemExit with a clear message if the current tier is too low.

    Args:
        required: Minimum tier needed (1, 2, or 3).
        feature: Human-readable description of the feature being gated.
    """
    current = get_tier()
    if current >= required:
        return

    from rich.console import Console
    _console = Console(stderr=True)

    missing: list[str] = []
    if required >= 2 and not any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL")):
        missing.append("LLM API key — run [bold]applypilot init[/bold] or set GEMINI_API_KEY")
    if required >= 3:
        if not shutil.which("claude"):
            missing.append("Claude Code CLI — install from [bold]https://claude.ai/code[/bold]")
        try:
            get_chrome_path()
        except FileNotFoundError:
            missing.append("Chrome/Chromium — install or set CHROME_PATH")

    _console.print(
        f"\n[red]'{feature}' requires {TIER_LABELS.get(required, f'Tier {required}')} (Tier {required}).[/red]\n"
        f"Current tier: {TIER_LABELS.get(current, f'Tier {current}')} (Tier {current})."
    )
    if missing:
        _console.print("\n[yellow]Missing:[/yellow]")
        for m in missing:
            _console.print(f"  - {m}")
    _console.print()
    raise SystemExit(1)
