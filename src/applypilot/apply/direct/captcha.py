"""CapSolver integration for Direct Apply (reCAPTCHA v2, hCaptcha, Turnstile; skip invisible v3)."""

from __future__ import annotations

import logging
import os
import time

import httpx

from applypilot.apply import apply_settings, prompt_scripts

logger = logging.getLogger(__name__)

_CAPSOLVER_API = "https://api.capsolver.com"
_TASK_TYPE_V2 = "ReCaptchaV2TaskProxyLess"
_TASK_TYPE_HCAPTCHA = "HCaptchaTaskProxyLess"
_TASK_TYPE_TURNSTILE = "AntiTurnstileTaskProxyLess"
_POLL_INTERVAL_S = 2.0
_MAX_POLL_S = 120.0

_SOLVABLE_TYPES = frozenset({"recaptchav2", "hcaptcha", "turnstile"})
_SKIP_TYPES = frozenset({"recaptchav3", "turnstile_script_only"})


def captcha_api_key() -> str:
    return (os.environ.get("CAPSOLVER_API_KEY") or "").strip()


def detect_captcha(page) -> dict | None:
    """Return {type, sitekey, url} or None."""
    try:
        return page.evaluate(prompt_scripts.captcha_detect_eval_js())
    except Exception:  # noqa: BLE001
        logger.debug("captcha detect evaluate failed", exc_info=True)
        return None


def _enrich_turnstile_info(page, info: dict) -> dict:
    """Pull Turnstile sitekey from page config when the widget has not rendered yet."""
    if str(info.get("sitekey") or "").strip():
        return info
    try:
        sitekey = page.evaluate(
            """() => {
              try {
                const wk = window.careers?.config?.turnstileWidgetSiteKey;
                if (wk) return wk;
              } catch (e) {}
              for (const s of document.querySelectorAll('script:not([src])')) {
                const m = (s.textContent || '').match(
                  /turnstileWidgetSiteKey["']\\s*:\\s*["']([^"']+)/
                );
                if (m) return m[1];
              }
              return '';
            }"""
        )
        if sitekey:
            enriched = dict(info)
            enriched["type"] = "turnstile"
            enriched["sitekey"] = str(sitekey)
            return enriched
    except Exception:  # noqa: BLE001
        logger.debug("turnstile sitekey enrich failed", exc_info=True)
    return info


def detect_captcha_blocking(page, *, wait_s: float = 3.0) -> dict | None:
    """Detect captcha; wait briefly when only the Turnstile loader script is present."""
    info = detect_captcha(page)
    if info:
        info = _enrich_turnstile_info(page, info)
    if not info:
        return None
    ctype = (info.get("type") or "").lower()
    if ctype != "turnstile_script_only" or wait_s <= 0:
        return info
    try:
        page.wait_for_timeout(int(wait_s * 1000))
    except Exception:  # noqa: BLE001
        pass
    info = detect_captcha(page) or info
    return _enrich_turnstile_info(page, info)


def is_blocking_captcha(info: dict | None) -> bool:
    """True when captcha metadata is a solvable wall (not v3 / script-only)."""
    if not info:
        return False
    ctype = (info.get("type") or "").lower()
    return ctype not in _SKIP_TYPES and ctype in _SOLVABLE_TYPES


def turnstile_wall_visible(page) -> bool:
    """True when a Cloudflare Turnstile human-check is visible on the page."""
    info = detect_captcha_blocking(page, wait_s=0)
    if info and (info.get("type") or "").lower() in {"turnstile", "turnstile_script_only"}:
        return True
    try:
        return bool(
            page.evaluate(
                """() => {
                  if (document.querySelector(
                    '.cf-turnstile, iframe[src*="challenges.cloudflare.com"], [data-turnstile-sitekey]'
                  )) return true;
                  const body = (document.body && document.body.innerText) || '';
                  return /verify you are human/i.test(body);
                }"""
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _create_task(
    api_key: str,
    *,
    task_type: str,
    sitekey: str,
    page_url: str,
    metadata: dict | None = None,
) -> str | None:
    task: dict = {
        "type": task_type,
        "websiteURL": page_url,
        "websiteKey": sitekey,
    }
    if metadata:
        task["metadata"] = metadata
    payload = {
        "clientKey": api_key,
        "task": task,
    }
    try:
        resp = httpx.post(
            f"{_CAPSOLVER_API}/createTask",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorId"):
            logger.warning("CapSolver createTask error: %s", data)
            return None
        return str(data.get("taskId") or "") or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("CapSolver createTask failed: %s", exc)
        return None


def _solution_token(solution: dict) -> str | None:
    for key in ("gRecaptchaResponse", "token", "hCaptchaResponse"):
        val = solution.get(key)
        if val:
            return str(val)
    return None


def _poll_task(api_key: str, task_id: str) -> str | None:
    deadline = time.monotonic() + _MAX_POLL_S
    while time.monotonic() < deadline:
        try:
            resp = httpx.post(
                f"{_CAPSOLVER_API}/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errorId"):
                logger.warning("CapSolver poll error: %s", data)
                return None
            status = (data.get("status") or "").lower()
            if status == "ready":
                solution = data.get("solution") or {}
                return _solution_token(solution)
            if status == "failed":
                return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("CapSolver poll: %s", exc)
        time.sleep(_POLL_INTERVAL_S)
    return None


def _inject_token(page, ctype: str, token: str) -> bool:
    if ctype == "hcaptcha":
        js = prompt_scripts.captcha_inject_hcaptcha_eval_js(token)
    elif ctype == "turnstile":
        js = prompt_scripts.captcha_inject_turnstile_eval_js(token)
    else:
        js = prompt_scripts.captcha_inject_recaptcha_eval_js(token)
    try:
        ok = page.evaluate(js)
        if ctype in {"hcaptcha", "turnstile"}:
            return bool(ok)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("%s inject failed", ctype, exc_info=True)
        return False


def _task_type_for(ctype: str) -> str | None:
    if ctype == "recaptchav2":
        return _TASK_TYPE_V2
    if ctype == "hcaptcha":
        return _TASK_TYPE_HCAPTCHA
    if ctype == "turnstile":
        return _TASK_TYPE_TURNSTILE
    return None


def _turnstile_metadata(info: dict) -> dict | None:
    meta: dict = {}
    action = info.get("action")
    cdata = info.get("cdata")
    if action:
        meta["action"] = action
    if cdata:
        meta["cdata"] = cdata
    return meta or None


def solve_captcha_if_present(page, *, api_key: str | None = None) -> bool:
    """Return True if no blocking captcha, solved, or skippable (v3)."""
    info = detect_captcha_blocking(page)
    if not info:
        return True

    ctype = (info.get("type") or "").lower()
    if ctype in _SKIP_TYPES:
        if ctype == "turnstile_script_only" and turnstile_wall_visible(page):
            page.wait_for_timeout(3000)
            info = _enrich_turnstile_info(page, detect_captcha(page) or info)
            ctype = (info.get("type") or "").lower()
            if ctype == "turnstile_script_only":
                logger.warning("Turnstile wall visible but sitekey not exposed")
                return False
        else:
            return True
    if ctype not in _SOLVABLE_TYPES:
        logger.info("Unsupported captcha type for direct solve: %s", ctype)
        return False

    if not apply_settings.captcha_solving_enabled():
        if not captcha_api_key().strip():
            logger.warning(
                "CapSolver skipped: CAPSOLVER_API_KEY is empty in ~/.applypilot/.env"
            )
        else:
            logger.info("CapSolver disabled (APPLYPILOT_DIRECT_CAPTCHA=0)")
        return False

    key = (api_key or captcha_api_key()).strip()
    if not key:
        logger.warning(
            "CapSolver skipped: CAPSOLVER_API_KEY is empty in ~/.applypilot/.env"
        )
        return False

    sitekey = str(info.get("sitekey") or "").strip()
    page_url = str(info.get("url") or page.url or "").strip()
    if not sitekey or not page_url:
        return False

    task_type = _task_type_for(ctype)
    if not task_type:
        return False

    metadata = _turnstile_metadata(info) if ctype == "turnstile" else None
    task_id = _create_task(
        key,
        task_type=task_type,
        sitekey=sitekey,
        page_url=page_url,
        metadata=metadata,
    )
    if not task_id:
        return False
    token = _poll_task(key, task_id)
    if not token:
        return False
    return _inject_token(page, ctype, token)


def solve_recaptcha_v2_if_present(page, *, api_key: str | None = None) -> bool:
    """Backward-compatible alias for verification-wall path."""
    return solve_captcha_if_present(page, api_key=api_key)
