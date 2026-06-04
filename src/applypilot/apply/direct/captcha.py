"""CapSolver integration for Direct Apply (reCAPTCHA v2 only; skip invisible v3)."""

from __future__ import annotations

import logging
import os
import time

import httpx

from applypilot.apply import prompt_scripts

logger = logging.getLogger(__name__)

_CAPSOLVER_API = "https://api.capsolver.com"
_TASK_TYPE_V2 = "ReCaptchaV2TaskProxyLess"
_POLL_INTERVAL_S = 2.0
_MAX_POLL_S = 120.0


def captcha_api_key() -> str:
    return (os.environ.get("CAPSOLVER_API_KEY") or "").strip()


def detect_captcha(page) -> dict | None:
    """Return {type, sitekey, url} or None. v3 is reported but not blocking."""
    try:
        return page.evaluate(prompt_scripts.CAPTCHA_DETECT_JS)
    except Exception:  # noqa: BLE001
        return None


def _create_task(api_key: str, *, sitekey: str, page_url: str) -> str | None:
    payload = {
        "clientKey": api_key,
        "task": {
            "type": _TASK_TYPE_V2,
            "websiteURL": page_url,
            "websiteKey": sitekey,
        },
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
                token = solution.get("gRecaptchaResponse") or solution.get("token")
                return str(token) if token else None
            if status == "failed":
                return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("CapSolver poll: %s", exc)
        time.sleep(_POLL_INTERVAL_S)
    return None


def _inject_recaptcha(page, token: str) -> bool:
    js = prompt_scripts.CAPTCHA_INJECT_RECAPTCHA_JS.replace("THE_TOKEN", token)
    try:
        page.evaluate(js)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("reCAPTCHA inject failed", exc_info=True)
        return False


def solve_recaptcha_v2_if_present(page, *, api_key: str | None = None) -> bool:
    """Detect and solve a visible reCAPTCHA v2 challenge. Returns True if solved or absent."""
    key = (api_key or captcha_api_key()).strip()
    if not key:
        return False

    info = detect_captcha(page)
    if not info:
        return True
    ctype = (info.get("type") or "").lower()
    if ctype == "recaptchav3":
        return True  # invisible v3 must not block submit
    if ctype != "recaptchav2":
        return False

    sitekey = str(info.get("sitekey") or "").strip()
    page_url = str(info.get("url") or page.url or "").strip()
    if not sitekey or not page_url:
        return False

    task_id = _create_task(key, sitekey=sitekey, page_url=page_url)
    if not task_id:
        return False
    token = _poll_task(key, task_id)
    if not token:
        return False
    return _inject_recaptcha(page, token)
