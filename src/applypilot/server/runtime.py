"""Start/stop/status for a detached dashboard watchdog."""

from __future__ import annotations

import os
import plistlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DAEMON_PIDFILE = Path.home() / ".applypilot" / "dashboard-serve-daemon.pid"
LOG_PATH = Path.home() / ".applypilot" / "logs" / "dashboard-serve.log"
LAUNCH_AGENT_LABEL = "com.applypilot.dashboard"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def python_executable() -> str:
    return sys.executable


def load_dotenv_into(environ: dict[str, str]) -> None:
    env_file = Path.home() / ".applypilot" / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in environ:
            environ[key] = value.strip()


def read_pid(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_http_up(host: str, port: int) -> bool:
    for path in ("/health", "/"):
        url = f"http://{host}:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
    return False


def _serve_pids() -> list[int]:
    try:
        out = subprocess.check_output(["pgrep", "-f", "applypilot.server.runtime run"], text=True)
    except subprocess.CalledProcessError:
        return []
    return [int(line) for line in out.splitlines() if line.strip().isdigit()]


def stop() -> tuple[bool, str]:
    pid = read_pid(DAEMON_PIDFILE)
    if pid is not None and process_alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not process_alive(pid):
                break
            time.sleep(0.25)
        if process_alive(pid):
            os.kill(pid, signal.SIGKILL)
    DAEMON_PIDFILE.unlink(missing_ok=True)
    for orphan in _serve_pids():
        if process_alive(orphan):
            os.kill(orphan, signal.SIGTERM)
    return True, "Dashboard stopped"


def start(host: str = "127.0.0.1", port: int = 9477) -> tuple[bool, str]:
    pid = read_pid(DAEMON_PIDFILE)
    if pid is not None and process_alive(pid):
        url = f"http://{host}:{port}/"
        if is_http_up(host, port):
            return True, f"Already running (pid {pid}) — {url}"
        return True, f"Daemon pid {pid} alive but HTTP not ready — tail {LOG_PATH}"

    stop()

    env = os.environ.copy()
    load_dotenv_into(env)
    env["APPLYPILOT_SERVE_HOST"] = host
    env["APPLYPILOT_SERVE_PORT"] = str(port)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_PATH.open("a", encoding="utf-8")

    proc = subprocess.Popen(
        [python_executable(), "-m", "applypilot.server.runtime", "run"],
        cwd=str(repo_root()),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    DAEMON_PIDFILE.write_text(str(proc.pid), encoding="utf-8")

    url = f"http://{host}:{port}/"
    for _ in range(20):
        time.sleep(1)
        if is_http_up(host, port):
            return True, f"Started (pid {proc.pid}) — {url}\nLog: {LOG_PATH}"
    return True, f"Started (pid {proc.pid}) but HTTP not ready yet — tail {LOG_PATH}"


def status(host: str = "127.0.0.1", port: int = 9477) -> str:
    lines: list[str] = []
    pid = read_pid(DAEMON_PIDFILE)
    if pid is not None and process_alive(pid):
        lines.append(f"daemon: running (pid {pid})")
    else:
        lines.append("daemon: not running")
        if DAEMON_PIDFILE.is_file():
            lines.append(f"  (stale pid file: {DAEMON_PIDFILE.read_text(encoding='utf-8').strip()})")

    runtime_pids = _serve_pids()
    if runtime_pids:
        lines.append(f"watchdog: {', '.join(str(p) for p in runtime_pids)}")
    else:
        lines.append("watchdog: not running")

    url = f"http://{host}:{port}/"
    if is_http_up(host, port):
        lines.append(f"http: OK {url}")
    else:
        lines.append("http: down")
    lines.append(f"log: {LOG_PATH}")
    if LAUNCH_AGENT_PATH.is_file():
        lines.append(f"launchagent: installed ({LAUNCH_AGENT_PATH})")
    return "\n".join(lines)


def install_launch_agent(host: str = "127.0.0.1", port: int = 9477) -> tuple[bool, str]:
    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            python_executable(),
            "-m",
            "applypilot.server.runtime",
            "run",
        ],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": {
            "APPLYPILOT_SERVE_HOST": host,
            "APPLYPILOT_SERVE_PORT": str(port),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "ProcessType": "Background",
    }
    load_dotenv_into(plist["EnvironmentVariables"])
    with LAUNCH_AGENT_PATH.open("wb") as handle:
        plistlib.dump(plist, handle)

    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(LAUNCH_AGENT_PATH)], check=False)
    loaded = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(LAUNCH_AGENT_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    if loaded.returncode != 0:
        return False, f"Failed to load LaunchAgent: {loaded.stderr.strip() or loaded.stdout.strip()}"
    return True, f"LaunchAgent installed — {LAUNCH_AGENT_PATH}"


def uninstall_launch_agent() -> tuple[bool, str]:
    uid = os.getuid()
    if LAUNCH_AGENT_PATH.is_file():
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(LAUNCH_AGENT_PATH)], check=False)
        LAUNCH_AGENT_PATH.unlink(missing_ok=True)
    stop()
    return True, "LaunchAgent removed and dashboard stopped"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "status"
    host = os.environ.get("APPLYPILOT_SERVE_HOST", "127.0.0.1")
    port = int(os.environ.get("APPLYPILOT_SERVE_PORT", "9477"))

    if cmd == "run":
        from applypilot.server.daemon import supervise

        supervise()
        return 0

    if cmd == "start":
        ok, message = start(host=host, port=port)
        print(message)
        return 0 if ok else 1

    if cmd == "stop":
        _, message = stop()
        print(message)
        return 0

    if cmd == "restart":
        stop()
        time.sleep(1)
        ok, message = start(host=host, port=port)
        print(message)
        return 0 if ok else 1

    if cmd == "status":
        print(status(host=host, port=port))
        return 0

    if cmd == "install-launchagent":
        ok, message = install_launch_agent(host=host, port=port)
        print(message)
        return 0 if ok else 1

    if cmd == "uninstall-launchagent":
        _, message = uninstall_launch_agent()
        print(message)
        return 0

    print(
        "Usage: python -m applypilot.server.runtime "
        "{start|stop|restart|status|install-launchagent|uninstall-launchagent|run}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
