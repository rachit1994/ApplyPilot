"""Human-in-the-loop login gate for Direct Apply.

When the deterministic Driver lands on a provider's login wall, it can't proceed
without you signing in. Instead of failing, it registers the blocked domain here
and the job is parked ``awaiting_login`` (reversible). You log in once in the
visible Chrome, then **Resume** from the dashboard (or CLI) — the gate clears and
the parked jobs for that domain re-enter the queue, now behind your session.

State lives in a JSON file under APP_DIR so the apply run (one process) and the
dashboard/CLI resume (another process) share it. Writes are atomic.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _state_path() -> Path:
    from applypilot import config

    return Path(config.APP_DIR) / "login_gate.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {"paused": False, "generation": 0, "pending": {}}


def _read() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("paused", False)
    data.setdefault("generation", 0)
    data.setdefault("pending", {})
    if not isinstance(data["pending"], dict):
        data["pending"] = {}
    return data


def _write(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".login_gate_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def request_login(
    domain: str,
    *,
    url: str = "",
    reason: str = "login_required",
    has_google_signin: bool | None = None,
) -> dict[str, Any]:
    """Register a domain that needs a human login; pauses the gate."""
    domain = (domain or "").strip().lower()
    if not domain:
        return snapshot()
    with _LOCK:
        data = _read()
        existing = data["pending"].get(domain) or {}
        data["pending"][domain] = {
            "url": url or existing.get("url", ""),
            "reason": reason,
            "has_google_signin": bool(has_google_signin)
            if has_google_signin is not None
            else existing.get("has_google_signin"),
            "since": existing.get("since") or _now(),
        }
        data["paused"] = True
        _write(data)
        return data


def pending() -> list[dict[str, Any]]:
    """List domains currently awaiting a human login."""
    data = _read()
    return [
        {"domain": dom, **(info if isinstance(info, dict) else {})}
        for dom, info in data.get("pending", {}).items()
    ]


def is_paused() -> bool:
    data = _read()
    return bool(data.get("paused")) and bool(data.get("pending"))


def is_domain_pending(domain: str) -> bool:
    domain = (domain or "").strip().lower()
    return domain in _read().get("pending", {})


def resume(domain: str | None = None) -> dict[str, Any]:
    """Clear a pending login (one domain, or all). Bumps generation so waiters wake."""
    with _LOCK:
        data = _read()
        if domain:
            data["pending"].pop((domain or "").strip().lower(), None)
        else:
            data["pending"] = {}
        if not data["pending"]:
            data["paused"] = False
        data["generation"] = int(data.get("generation", 0)) + 1
        data["resumed_at"] = _now()
        _write(data)
        return data


def clear() -> None:
    with _LOCK:
        _write(_empty())


def snapshot() -> dict[str, Any]:
    return _read()


def wait_for_resume(domain: str, *, timeout_s: float = 1800.0, poll_s: float = 3.0) -> bool:
    """Block until ``domain`` is no longer pending (you resumed), or timeout."""
    domain = (domain or "").strip().lower()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not is_domain_pending(domain):
            return True
        time.sleep(poll_s)
    return False
