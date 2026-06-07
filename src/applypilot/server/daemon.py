"""Restart loop for the dashboard uvicorn process."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
LOG_PATH = Path.home() / ".applypilot" / "logs" / "dashboard-serve.log"


def _log_line(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"=== {message} {stamp} ===\n")


def run_forever() -> None:
    """Run uvicorn until SIGTERM; caller restarts after return."""
    host = os.environ.get("APPLYPILOT_SERVE_HOST", "127.0.0.1")
    port = int(os.environ.get("APPLYPILOT_SERVE_PORT", "9477"))

    from applypilot.cli import _bootstrap
    import uvicorn

    from applypilot.server.app import create_app

    _bootstrap()
    _log_line(f"dashboard serve start on {host}:{port}")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


def supervise() -> None:
    """Watchdog: restart dashboard after exit or crash."""
    while True:
        try:
            run_forever()
            _log_line("dashboard serve exited cleanly")
        except Exception as exc:
            _log_line(f"dashboard serve crashed: {exc!r}")
        time.sleep(5)
