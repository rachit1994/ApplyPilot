"""Start and probe the local OpenOutreach REST API for ApplyPilot outreach."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from pathlib import Path

from applypilot.outreach.config import OutreachSettings, load_outreach_config
from applypilot.outreach.openoutreach_client import check_openoutreach_health

log = logging.getLogger(__name__)

PID_PATH_ENV = "APPLYPILOT_OPENOUTREACH_PID_FILE"
DEFAULT_PID_FILE = Path.home() / ".applypilot" / "openoutreach-api.pid"


def find_openoutreach_root() -> Path | None:
    """Locate an OpenOutreach checkout (manage.py + data/)."""
    candidates: list[Path] = []
    env_root = os.environ.get("OPENOUTREACH_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())

    applypilot_repo = Path(__file__).resolve().parents[3]
    candidates.extend(
        [
            applypilot_repo.parent / "OpenOutreach",
            applypilot_repo / "OpenOutreach",
            Path.cwd() / "OpenOutreach",
            Path.cwd().parent / "OpenOutreach",
        ]
    )

    seen: set[Path] = set()
    for raw in candidates:
        root = raw.resolve()
        if root in seen:
            continue
        seen.add(root)
        if (root / "manage.py").is_file() and (root / "data").is_dir():
            return root
    return None


def openoutreach_python(root: Path) -> Path:
    venv_py = root / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return venv_py
    raise FileNotFoundError(
        f"No .venv in {root}. Create one: cd {root} && python3 -m venv .venv && pip install -r requirements/base.txt"
    )


def build_openoutreach_env(settings: OutreachSettings) -> dict[str, str]:
    """Child process env: inherit host env but force API key/url from ApplyPilot config."""
    env = os.environ.copy()
    env["OPENOUTREACH_API_KEY"] = settings.openoutreach_api_key
    env.setdefault("OPENOUTREACH_API_HOST", "127.0.0.1")
    env.setdefault("OPENOUTREACH_API_PORT", "8741")
    if settings.openoutreach_base_url:
        env.setdefault("OPENOUTREACH_BASE_URL", settings.openoutreach_base_url)
    return env


def parse_base_url_port(base_url: str, *, default: int = 8741) -> tuple[str, int]:
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or default
    return host, port


def is_api_port_open(settings: OutreachSettings | None = None) -> bool:
    settings = settings or load_outreach_config()
    host, port = parse_base_url_port(settings.openoutreach_base_url)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def wait_for_health(
    settings: OutreachSettings,
    *,
    timeout_sec: float = 45.0,
    poll_sec: float = 0.5,
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_sec
    last = "timeout waiting for OpenOutreach"
    while time.monotonic() < deadline:
        ok, detail = check_openoutreach_health(
            settings.openoutreach_base_url,
            settings.openoutreach_api_key,
        )
        if ok:
            return True, detail
        last = detail
        if "cannot connect" not in detail.lower():
            return False, detail
        time.sleep(poll_sec)
    return False, last


def pid_file_path() -> Path:
    raw = os.environ.get(PID_PATH_ENV, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_PID_FILE


def read_pid_file() -> int | None:
    path = pid_file_path()
    if not path.is_file():
        return None
    try:
        return int(path.read_text().strip())
    except ValueError:
        return None


def write_pid_file(pid: int) -> None:
    path = pid_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def clear_pid_file() -> None:
    path = pid_file_path()
    if path.is_file():
        path.unlink()


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_api_server(
    *,
    settings: OutreachSettings | None = None,
    background: bool = True,
    wait: bool = True,
) -> tuple[bool, str]:
    """Start `manage.py runapi --no-daemon` with ApplyPilot's OPENOUTREACH_API_KEY."""
    settings = settings or load_outreach_config()
    if not settings.openoutreach_api_key:
        return False, "OPENOUTREACH_API_KEY not set in ~/.applypilot/.env"

    ok, detail = check_openoutreach_health(
        settings.openoutreach_base_url,
        settings.openoutreach_api_key,
    )
    if ok:
        return True, f"already running — {detail}"

    root = find_openoutreach_root()
    if root is None:
        return (
            False,
            "OpenOutreach repo not found. Set OPENOUTREACH_ROOT to your checkout "
            "(e.g. ../OpenOutreach) or clone eracle/OpenOutreach.",
        )

    try:
        python = openoutreach_python(root)
    except FileNotFoundError as exc:
        return False, str(exc)

    env = build_openoutreach_env(settings)
    log_path = Path.home() / ".applypilot" / "logs" / "openoutreach-api.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(python), "manage.py", "runapi", "--no-daemon"]
    if background:
        with log_path.open("a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(root),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        write_pid_file(proc.pid)
        if wait:
            ok, detail = wait_for_health(settings)
            if not ok:
                return False, f"started pid {proc.pid} but health check failed: {detail}"
            return True, f"started (pid {proc.pid}) — {detail}"
        return True, f"starting in background (pid {proc.pid}), log: {log_path}"

    proc = subprocess.run(cmd, cwd=str(root), env=env, check=False)
    if proc.returncode != 0:
        return False, f"runapi exited with code {proc.returncode} (see {log_path})"
    return True, "runapi finished"


def stop_api_server() -> tuple[bool, str]:
    pid = read_pid_file()
    if pid is None:
        return False, "no pid file — OpenOutreach was not started via applypilot openoutreach start"
    if not process_alive(pid):
        clear_pid_file()
        return True, f"stale pid {pid} removed (process not running)"
    try:
        os.kill(pid, 15)
    except OSError as exc:
        return False, f"could not stop pid {pid}: {exc}"
    clear_pid_file()
    return True, f"sent SIGTERM to pid {pid}"
