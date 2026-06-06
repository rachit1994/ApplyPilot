"""Closed-vocabulary browser action dispatch for self-learning apply.

Executor, recorder, and replayer share this table so every navigation step is
replayable without an LLM. Side-effecting tools are flagged for cache policy;
``submit`` is never cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from applypilot.apply.direct.unblock import (
    _GOOGLE_TEXTS,
    _click_any,
    _click_text,
    _dismiss_cookies,
    _has_identity_form,
)
from applypilot.apply.direct import extractor

# Closed vocabulary — every tool the unblock/replay tiers may emit.
ACTION_VOCABULARY: frozenset[str] = frozenset({
    "click",
    "login_google",
    "login_provider",
    "accept_cookies",
    "wait",
    "goto",
    "scroll",
    "wait_for_form",
    "next_page",
    "finish",
})

SIDE_EFFECTING_TOOLS: frozenset[str] = frozenset({
    "click",
    "login_google",
    "login_provider",
    "accept_cookies",
    "goto",
    "next_page",
    "scroll",
})

NEVER_CACHE_TOOLS: frozenset[str] = frozenset({"submit"})


@dataclass(frozen=True)
class ActionContext:
    """Runtime context for action execution."""

    goto_allowlist: frozenset[str] | None = None


@dataclass
class ActionResult:
    outcome: str
    advanced: bool
    error: str | None = None


def _field_count(snap: dict) -> int:
    return len(snap.get("fields") or [])


def _has_identity_fields(snap: dict) -> bool:
    from applypilot.apply.direct.unblock import has_identity_field

    fields = snap.get("fields") or []
    if len(fields) < 2:
        return False
    # Snapshot fields are dicts with a label key; wrap minimally for the helper.
    class _F:
        def __init__(self, label: str):
            self.label = label

    return has_identity_field(_F(f.get("label", "")) for f in fields)


def detect_advanced(before_snap: dict, after_snap: dict) -> bool:
    """True when the page moved toward an application form."""
    before_fields = _field_count(before_snap)
    after_fields = _field_count(after_snap)
    if after_fields > before_fields:
        return True
    if _has_identity_fields(after_snap) and not _has_identity_fields(before_snap):
        return True
    if before_snap.get("has_password_field") and not after_snap.get("has_password_field"):
        return True
    return False


def _url_allowed(url: str, allowlist: frozenset[str] | None) -> bool:
    if allowlist is None:
        return True
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host:
        return False
    for entry in allowlist:
        needle = entry.lower().strip()
        if not needle:
            continue
        if host == needle or host.endswith("." + needle) or host.endswith(needle):
            return True
        if url.startswith(needle):
            return True
    return False


def _result(outcome: str, *, advanced: bool = False, error: str | None = None) -> ActionResult:
    return ActionResult(outcome=outcome, advanced=advanced, error=error)


def execute(page, action: dict, *, context: ActionContext | None = None) -> ActionResult:
    """Dispatch one action dict ``{tool, args}`` against a Playwright page."""
    ctx = context or ActionContext()
    tool = (action.get("tool") or "").strip().lower()
    args = action.get("args") or {}

    try:
        if tool == "click":
            ok = _click_text(page, args.get("text", ""))
            return _result("clicked" if ok else "click_miss")

        if tool in ("login_google", "login_provider"):
            name = (args.get("name") or "google").strip().lower()
            if name in ("google", ""):
                ok = _click_any(page, _GOOGLE_TEXTS)
                return _result("google" if ok else "google_miss")
            ok = _click_text(page, name) or _click_any(page, (name,))
            return _result("provider" if ok else "provider_miss")

        if tool == "accept_cookies":
            ok = _dismiss_cookies(page)
            return _result("cookies" if ok else "cookies_miss")

        if tool == "wait":
            page.wait_for_timeout(2_500)
            return _result("waited")

        if tool == "goto":
            url = (args.get("url") or "").strip()
            if not url.startswith("http"):
                return _result("goto_bad_url", error="url must start with http")
            if not _url_allowed(url, ctx.goto_allowlist):
                return _result("goto_blocked", error="url not in goto_allowlist")
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1_500)
            return _result("navigated")

        if tool == "scroll":
            page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.8))")
            page.wait_for_timeout(500)
            return _result("scrolled")

        if tool == "wait_for_form":
            timeout_ms = int(args.get("timeout") or args.get("timeout_ms") or 8_000)
            deadline_ms = max(500, timeout_ms)
            waited = 0
            while waited < deadline_ms:
                if _has_identity_form(extractor.extract_fields(page)):
                    return _result("form_ready", advanced=True)
                page.wait_for_timeout(500)
                waited += 500
            return _result("wait_for_form_timeout")

        if tool == "next_page":
            texts = args.get("texts") or (
                "Next",
                "Continue",
                "Save and continue",
                "Save & continue",
                "Next step",
                "Proceed",
                "Review",
            )
            if isinstance(texts, str):
                texts = (texts,)
            for text in texts:
                if _click_text(page, str(text)):
                    return _result("next_page", advanced=True)
            return _result("next_page_miss")

        if tool == "finish":
            status = (args.get("status") or "blocked").strip().lower()
            advanced = status == "form_ready"
            return _result(status, advanced=advanced)

    except Exception as exc:  # noqa: BLE001
        return _result(f"error:{str(exc)[:60]}", error=str(exc)[:200])

    return _result("unknown_tool", error=f"unsupported tool: {tool}")
