"""Gemini unblock tier — surface a real application form when the deterministic
driver hits a *structural* block (no form, wrong form, login wall, JS app form
not yet mounted).

The deterministic Driver (driver.py) fills and submits any form whose fields it
can read. What it cannot do is *navigate*: click the right "Apply" button on a
job-board landing page, follow an off-page link to the real ATS, dismiss a
cookie wall, sign in with Google, or wait out a slow JS mount. Those are
single-decision navigation problems — cheap for an LLM, wasteful for Claude.

This tier hands Gemini a compact page snapshot plus a catalog of prebuilt
browser primitives (the same click/fill/login actions the Driver uses) and lets
it pick ONE action per step, looping until the real application form is on
screen. It then returns control to the Driver, which does the careful
deterministic fill → verify → submit. Gemini never submits the application — it
only gets us to the form.

Cost: gemini-3.1-flash-lite, ~$0.04/M in + $0.16/M out. A typical unblock is
5–10 steps × ~2–3K tokens ≈ $0.005–0.02/job — ~10× cheaper than a Claude rescue
and not subject to Claude's daily/weekly subscription ceiling.

Disable with APPLYPILOT_DIRECT_UNBLOCK=0.
"""

from __future__ import annotations

import json
import logging
import os
import re

from applypilot.apply.direct import extractor

logger = logging.getLogger(__name__)

# How many navigation decisions Gemini may make before we give up and escalate.
_DEFAULT_MAX_STEPS = 8

# Identity-field hints: a snapshot with one of these labelled inputs is a real
# application form (mirror of driver._IDENTITY_LABEL_HINTS).
_IDENTITY_HINTS: tuple[str, ...] = (
    "first name", "last name", "full name", "your name", "given name",
    "family name", "surname", "email", "e-mail", "phone", "mobile",
    "resume", "cv", "résumé", "linkedin",
)

# Visible-text grab for anchors + buttons (the Driver's extractor only returns
# button/role=button/input-submit; navigation also needs <a> links).
_CLICKABLES_JS = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const seen = new Set();
  const out = [];
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  document.querySelectorAll('a, button, [role="button"], input[type="submit"], input[type="button"]')
    .forEach((el) => {
      if (!vis(el)) return;
      const t = norm(el.innerText || el.value || el.getAttribute('aria-label'));
      if (!t || t.length > 60) return;
      if (seen.has(t.toLowerCase())) return;
      seen.add(t.toLowerCase());
      out.push(t);
    });
  return out.slice(0, 40);
}"""

_GOOGLE_TEXTS = (
    "sign in with google", "continue with google", "log in with google",
    "sign up with google", "google",
)

_COOKIE_TEXTS = (
    "accept all", "accept cookies", "accept", "i accept", "agree", "got it",
    "allow all",
)

_SYSTEM_PROMPT = """You are a browser-navigation assistant for an automated job-application engine.
The engine can already FILL and SUBMIT any application form it can see. Your ONLY
job is to get the real application form for THIS job onto the screen — then stop.

You are given a snapshot of the current page (URL, title, clickable elements,
form fields). Pick ONE action that moves toward the application form. Typical
moves: click an "Apply" / "Apply now" / "Apply for this job" button or link,
dismiss a cookie banner, sign in with Google if a login wall blocks the form,
wait for a slow form to load, or navigate to an apply URL.

NEVER try to submit the application. NEVER invent fields. If the snapshot already
shows an application form (inputs for name/email/phone/resume), call finish with
status "form_ready". If the page is clearly NOT a job application and has no path
to one (404, expired, a generic marketing page, a login wall with no Google
option), call finish with status "blocked".

Hard rules:
- Do NOT call finish with "form_ready" unless the snapshot's form_fields list
  actually contains a name OR email OR resume input. A page with an "Apply" /
  "Apply Now" button but no such fields is NOT ready — you MUST click that
  button (or accept cookies / sign in first if one blocks it).
- If form_fields only shows cookie/consent checkboxes ("Cookie list search",
  "Switch Label", "checkbox label", "targeted advertising"), the real form is
  hidden behind a consent banner — call accept_cookies, then click Apply.
- Prefer accept_cookies → click "Apply"/"Apply Now" → wait, in that order.

Respond with ONE JSON object only, no prose:
{"thought": "<short>", "tool": "<name>", "args": {...}}

Tools:
- click            args: {"text": "<exact visible text of a clickable>"}
- login_google     args: {}                 (click a Google sign-in control)
- accept_cookies   args: {}                 (dismiss a cookie/consent banner)
- wait             args: {}                 (let a JS form finish mounting)
- goto             args: {"url": "<url>"}   (navigate; only to an apply/job URL)
- finish           args: {"status": "form_ready" | "blocked"}
"""


def unblock_enabled() -> bool:
    raw = os.environ.get("APPLYPILOT_DIRECT_UNBLOCK")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _has_identity_form(form: extractor.FormState) -> bool:
    """True when the current form is a real application form (≥2 fields, ≥1 identity)."""
    fields = form.fillable()
    if len(fields) < 2:
        return False
    for f in fields:
        label = (f.label or "").lower()
        if any(h in label for h in _IDENTITY_HINTS):
            return True
    return False


def has_identity_field(fields) -> bool:
    """Public helper for the Driver's pre-fill check."""
    for f in fields:
        label = (f.label or "").lower()
        if any(h in label for h in _IDENTITY_HINTS):
            return True
    return False


def _snapshot(page) -> dict:
    form = extractor.extract_fields(page)
    try:
        clickables = page.evaluate(_CLICKABLES_JS)
    except Exception:  # noqa: BLE001
        clickables = list(form.submit_candidates)
    try:
        has_pw = page.locator("input[type=password]").count() > 0
    except Exception:  # noqa: BLE001
        has_pw = False
    fields = [
        {"label": (f.label or "")[:60], "type": f.type or f.tag,
         "required": f.required, "filled": not f.empty}
        for f in form.fillable()[:25]
    ]
    return {
        "url": form.url or page.url,
        "title": form.title,
        "clickables": clickables,
        "fields": fields,
        "has_password_field": has_pw,
        "body_excerpt": (form.body_text or "")[:1200],
        "_form": form,
    }


def _snapshot_for_prompt(snap: dict, job: dict) -> str:
    payload = {
        "job_title": job.get("title"),
        "url": snap["url"],
        "page_title": snap["title"],
        "clickable_elements": snap["clickables"],
        "form_fields": snap["fields"],
        "has_password_field": snap["has_password_field"],
        "body_excerpt": snap["body_excerpt"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_action(raw: str) -> dict | None:
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(obj, dict) or "tool" not in obj:
        return None
    obj.setdefault("args", {})
    return obj


def _click_text(page, text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    getters = (
        lambda: page.get_by_role("button", name=text, exact=False).first,
        lambda: page.get_by_role("link", name=text, exact=False).first,
        lambda: page.get_by_text(text, exact=False).first,
        # Last resort: any element whose normalized text equals the target.
        lambda: page.locator(
            f"xpath=//*[normalize-space(.)={_xpath_literal(text)}]"
        ).last,
    )
    for getter in getters:
        try:
            loc = getter()
            if loc.count() == 0:
                continue
            try:
                loc.scroll_into_view_if_needed(timeout=2_000)
            except Exception:  # noqa: BLE001
                pass
            try:
                loc.click(timeout=4_000)
            except Exception:  # noqa: BLE001
                # Overlay/animation intercept — force the click past it.
                loc.click(timeout=3_000, force=True)
            page.wait_for_timeout(1_500)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _xpath_literal(s: str) -> str:
    """Quote a string for use as an XPath literal (handles embedded quotes)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat('" + "',\"'\",'".join(parts) + "')"


def _click_any(page, texts: tuple[str, ...]) -> bool:
    for t in texts:
        if _click_text(page, t):
            return True
    return False


# OneTrust + common consent-banner accept controls (id/selector based — text
# matching alone misses these because the button text varies by locale).
_COOKIE_SELECTORS = (
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "[aria-label='Accept All Cookies']",
    ".onetrust-close-btn-handler",
    "#truste-consent-button",
    "button[mode='primary']",
)


def _dismiss_cookies(page) -> bool:
    for sel in _COOKIE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=3_000)
                page.wait_for_timeout(800)
                return True
        except Exception:  # noqa: BLE001
            continue
    return _click_any(page, _COOKIE_TEXTS)


def _execute(page, action: dict) -> str:
    tool = (action.get("tool") or "").strip().lower()
    args = action.get("args") or {}
    try:
        if tool == "click":
            return "clicked" if _click_text(page, args.get("text", "")) else "click_miss"
        if tool == "login_google":
            return "google" if _click_any(page, _GOOGLE_TEXTS) else "google_miss"
        if tool == "accept_cookies":
            return "cookies" if _dismiss_cookies(page) else "cookies_miss"
        if tool == "wait":
            page.wait_for_timeout(2_500)
            return "waited"
        if tool == "goto":
            url = (args.get("url") or "").strip()
            if url.startswith("http"):
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1_500)
                return "navigated"
            return "goto_bad_url"
    except Exception as exc:  # noqa: BLE001
        return f"error:{str(exc)[:60]}"
    return "unknown_tool"


class GeminiQuotaExhausted(RuntimeError):
    """Raised when Gemini is rate-limited/quota-capped so callers can fall through."""


def _is_quota_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(
        m in s for m in ("429", "quota", "rate limit", "resource_exhausted", "exhausted")
    )


def gemini_unblock(
    page,
    job: dict,
    *,
    family: str,
    worker_id: int = 0,
    reason: str = "",
    max_steps: int | None = None,
) -> bool:
    """Drive Gemini to surface the real application form. Return True if visible.

    Raises GeminiQuotaExhausted when Gemini is rate-limited, so the caller can
    fall through to the next tier instead of treating it as a hard failure.
    """
    if not unblock_enabled():
        return False
    from applypilot.llm import get_gemini_client

    steps = max_steps if max_steps is not None else _DEFAULT_MAX_STEPS

    # Cheap deterministic warm-up: a stray cookie banner is the #1 thing hiding a
    # form, and it costs no tokens to dismiss before asking Gemini anything.
    _dismiss_cookies(page)
    if _has_identity_form(extractor.extract_fields(page)):
        return True

    try:
        client = get_gemini_client()
    except Exception as exc:  # noqa: BLE001
        logger.info("[W%d] Unblock: no Gemini client (%s)", worker_id, exc)
        return False

    logger.info(
        "[W%d] Unblock tier engaged on %s (reason=%s)", worker_id, family, reason
    )
    history: list[str] = []
    for step in range(steps):
        snap = _snapshot(page)
        if _has_identity_form(snap["_form"]):
            logger.info("[W%d] Unblock: form ready after %d step(s)", worker_id, step)
            return True
        prompt = (
            _SYSTEM_PROMPT
            + "\n\nPAGE SNAPSHOT:\n"
            + _snapshot_for_prompt(snap, job)
            + ("\n\nRECENT ACTIONS:\n" + " | ".join(history[-5:]) if history else "")
        )
        try:
            raw = client.ask(prompt, max_tokens=300, operation="apply_unblock")
        except Exception as exc:  # noqa: BLE001
            if _is_quota_error(exc):
                raise GeminiQuotaExhausted(str(exc)) from exc
            logger.info("[W%d] Unblock: Gemini call failed (%s)", worker_id, exc)
            return False
        action = _parse_action(raw)
        if not action:
            logger.info("[W%d] Unblock: unparseable action %r", worker_id, raw[:120])
            return _has_identity_form(extractor.extract_fields(page))
        tool = (action.get("tool") or "").lower()
        if tool == "finish":
            status = (action.get("args") or {}).get("status", "")
            ready = _has_identity_form(extractor.extract_fields(page))
            # A "blocked" verdict is final. A "form_ready" claim is only trusted
            # when a real identity form is actually present; otherwise Gemini
            # gave up too early — nudge it to navigate and keep going.
            if status == "blocked" or ready:
                logger.info(
                    "[W%d] Unblock: Gemini finished (%s, ready=%s)",
                    worker_id, status, ready,
                )
                return ready
            history.append("finish(form_ready) rejected: no identity form visible yet")
            logger.info("[W%d] Unblock: premature finish ignored, continuing", worker_id)
            page.wait_for_timeout(500)
            continue
        result = _execute(page, action)
        history.append(f"{tool}({(action.get('args') or {})})->{result}")
        logger.info("[W%d] Unblock step %d: %s -> %s", worker_id, step, tool, result)
        page.wait_for_timeout(800)

    final = _has_identity_form(extractor.extract_fields(page))
    logger.info("[W%d] Unblock: budget exhausted, form_ready=%s", worker_id, final)
    return final
