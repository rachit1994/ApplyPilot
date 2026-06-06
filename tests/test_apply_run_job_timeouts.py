"""Regression tests for apply hang fix: inactivity, wall, and fast-fail paths."""

from __future__ import annotations

import io
import json
import queue
import threading
import time
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from applypilot.apply import launcher
from applypilot.apply import prompt as prompt_mod

HANG_FIX_READY = (
    hasattr(launcher, "FAST_FAIL_TEXT_PATTERNS")
    and hasattr(launcher, "_detect_fast_fail")
    and "apply_inactivity_timeout" in launcher.config.DEFAULTS
)

pytestmark = pytest.mark.skipif(
    not HANG_FIX_READY,
    reason="apply hang fix not merged into launcher.py yet",
)


# ---------------------------------------------------------------------------
# Stream helpers
# ---------------------------------------------------------------------------

def _assistant_text(text: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }
    )


def _result_msg(text: str = "") -> str:
    return json.dumps(
        {
            "type": "result",
            "result": text,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "total_cost_usd": 0.01,
            "num_turns": 1,
        }
    )


APPLIED_RESULT_JSON = (
    'RESULT_JSON:{"status":"applied","submit_click_ref":"submit-ref",'
    '"submit_button_text":"Send","pre_submit_url":"https://jobs.example/apply",'
    '"post_submit_url":"https://jobs.example/thanks",'
    '"post_submit_snapshot":{"fieldCount":0,"fields":[]},'
    '"confirmation_copy":"Application received"}'
)


class ControllableStdout:
    """Blocking stdout stand-in: feed lines from tests, block until fed or closed."""

    def __init__(self) -> None:
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._closed = False

    def feed(self, line: str) -> None:
        self._lines.put(line)

    def close_feed(self) -> None:
        if not self._closed:
            self._closed = True
            self._lines.put(None)

    def __iter__(self) -> Iterator[str]:
        while True:
            item = self._lines.get()
            if item is None:
                break
            yield item + "\n"


class FakePopen:
    """Minimal subprocess.Popen stub with controllable stdout."""

    def __init__(self, stdout: ControllableStdout, *, pid: int = 4242) -> None:
        self.stdout = stdout
        self.stdin = io.StringIO()
        self.pid = pid
        self.returncode: int | None = None
        self._waited = False

    def wait(self, timeout: float | None = None) -> int:
        self._waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_job_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate config, stub chrome/prompt/dashboard, capture kill calls."""
    from applypilot import config
    from applypilot.apply import dashboard

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    worker_dir = tmp_path / "worker-0"
    worker_dir.mkdir(parents=True, exist_ok=True)

    killed: list[int] = []
    monkeypatch.setattr(launcher, "_kill_process_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(launcher, "reset_worker_dir", lambda _wid: worker_dir)
    monkeypatch.setattr(prompt_mod, "build_prompt", lambda **kwargs: "mock prompt")
    monkeypatch.setattr(dashboard, "init_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "update_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "add_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "get_state", lambda *args, **kwargs: None)

    job = {
        "url": "https://jobs.example.com/role",
        "title": "Founding Engineer",
        "site": "ExampleCo",
        "application_url": "https://jobs.example.com/role/apply",
        "tailored_resume_path": str(tmp_path / "resume.pdf"),
        "fit_score": 9,
    }
    resume_txt = Path(job["tailored_resume_path"]).with_suffix(".txt")
    resume_txt.write_text("Senior engineer resume", encoding="utf-8")

    return {
        "job": job,
        "killed": killed,
        "config": config,
        "monkeypatch": monkeypatch,
    }


def _install_fake_popen(monkeypatch: pytest.MonkeyPatch, stdout: ControllableStdout) -> FakePopen:
    fake = FakePopen(stdout)

    def _popen_factory(*args, **kwargs):
        return fake

    monkeypatch.setattr(launcher.subprocess, "Popen", _popen_factory)
    return fake


def _install_capturing_fake_popen(
    monkeypatch: pytest.MonkeyPatch,
    stdout: ControllableStdout,
) -> tuple[FakePopen, dict]:
    fake = FakePopen(stdout)
    captured: dict = {}

    def _popen_factory(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake

    monkeypatch.setattr(launcher.subprocess, "Popen", _popen_factory)
    return fake, captured


# ---------------------------------------------------------------------------
# Fast-fail unit tests
# ---------------------------------------------------------------------------

def test_detect_fast_fail_quota_text():
    reason = launcher._detect_fast_fail(
        "You've hit your limit · resets 11am (Asia/Calcutta)"
    )
    assert reason == "claude_quota_exhausted"


def test_detect_fast_fail_auth_text():
    reason = launcher._detect_fast_fail("Please run `claude login` to continue")
    assert reason == "claude_auth_failed"


def test_detect_fast_fail_benign_rate_limited_text():
    """Job/API context mentioning rate limits must not trigger quota fast-fail."""
    reason = launcher._detect_fast_fail(
        "The API is rate limited for this endpoint"
    )
    assert reason is None


def test_fast_fail_patterns_include_quota_and_auth():
    assert "claude_quota_exhausted" in launcher.FAST_FAIL_TEXT_PATTERNS
    assert "claude_auth_failed" in launcher.FAST_FAIL_TEXT_PATTERNS


def test_inactivity_and_wall_timeout_are_permanent_failures():
    assert launcher._is_permanent_failure("failed:inactivity_timeout")
    assert launcher._is_permanent_failure("failed:wall_timeout")


# ---------------------------------------------------------------------------
# run_job timeout / fast-fail integration tests
# ---------------------------------------------------------------------------

def test_run_job_inactivity_timeout_when_proc_emits_nothing(run_job_env):
    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 0.15)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 5.0)

    stdout = ControllableStdout()
    _install_fake_popen(env["monkeypatch"], stdout)

    t0 = time.monotonic()
    status, duration_ms, log_path = launcher.run_job(env["job"], port=9222, worker_id=0)
    elapsed = time.monotonic() - t0

    assert status == "failed:inactivity_timeout"
    assert log_path is None
    assert duration_ms >= 0
    assert elapsed < 2.0
    assert env["killed"] == [4242]


def test_run_job_fast_fail_on_quota_line(run_job_env):
    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 5.0)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 30.0)

    stdout = ControllableStdout()
    _install_fake_popen(env["monkeypatch"], stdout)

    def _emit_quota_then_stall() -> None:
        stdout.feed(
            _assistant_text("You've hit your limit · resets 11am (Asia/Calcutta)")
        )

    threading.Thread(target=_emit_quota_then_stall, daemon=True).start()

    t0 = time.monotonic()
    status, duration_ms, log_path = launcher.run_job(env["job"], port=9222, worker_id=0)
    elapsed = time.monotonic() - t0

    assert status.startswith("failed:claude_quota_exhausted:")
    assert log_path is None
    assert elapsed < 2.0
    assert env["killed"] == [4242]


def test_run_job_launches_claude_in_separate_session(run_job_env):
    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 2.0)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 10.0)
    env["monkeypatch"].setattr(launcher.platform, "system", lambda: "Darwin")

    stdout = ControllableStdout()
    _fake, captured = _install_capturing_fake_popen(env["monkeypatch"], stdout)

    def _emit_success() -> None:
        applied_body = (
            ">> browser_click submit-ref Send\n"
            f"{APPLIED_RESULT_JSON}\n"
        )
        stdout.feed(_assistant_text(applied_body))
        stdout.feed(_result_msg(applied_body))
        stdout.close_feed()

    threading.Thread(target=_emit_success, daemon=True).start()

    status, _duration_ms, _log_path = launcher.run_job(
        env["job"], port=9222, worker_id=0
    )

    assert status == "applied"
    assert captured["kwargs"]["start_new_session"] is True


def test_run_job_wall_timeout_with_steady_output(run_job_env):
    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 0.5)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 0.25)

    stdout = ControllableStdout()
    _install_fake_popen(env["monkeypatch"], stdout)

    stop = threading.Event()

    def _steady_heartbeat() -> None:
        while not stop.is_set():
            stdout.feed(_assistant_text("still working"))
            time.sleep(0.05)

    feeder = threading.Thread(target=_steady_heartbeat, daemon=True)
    feeder.start()

    try:
        status, duration_ms, log_path = launcher.run_job(
            env["job"], port=9222, worker_id=0
        )
    finally:
        stop.set()
        stdout.close_feed()

    assert status == "failed:wall_timeout"
    assert log_path is None
    assert duration_ms >= 200
    assert env["killed"] == [4242]


def test_run_job_fast_fail_counts_claude_attempt_in_governor(run_job_env):
    """Aborted Claude runs must still count against the per-run budget governor."""
    from applypilot.apply import apply_budget

    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 5.0)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 30.0)
    apply_budget.governor().reset()

    stdout = ControllableStdout()
    _install_fake_popen(env["monkeypatch"], stdout)
    threading.Thread(
        target=lambda: stdout.feed(
            _assistant_text("You've hit your limit · resets 11am (Asia/Calcutta)")
        ),
        daemon=True,
    ).start()

    status, _duration_ms, _log_path = launcher.run_job(
        env["job"], port=9222, worker_id=0
    )

    assert status.startswith("failed:claude_quota_exhausted")
    snap = apply_budget.governor().snapshot()
    assert snap.claude_attempts == 1


def test_run_job_success_counts_single_claude_attempt(run_job_env):
    """A successful run counts exactly one attempt and records its cost once."""
    from applypilot.apply import apply_budget

    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 2.0)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 10.0)
    env["monkeypatch"].setattr(
        launcher.apply_settings, "require_gmail_confirmation", lambda: False
    )
    apply_budget.governor().reset()

    stdout = ControllableStdout()
    _install_fake_popen(env["monkeypatch"], stdout)
    applied_body = ">> browser_click submit-ref Send\n" f"{APPLIED_RESULT_JSON}\n"

    def _emit_success() -> None:
        stdout.feed(_assistant_text(applied_body))
        stdout.feed(_result_msg(applied_body))
        stdout.close_feed()

    threading.Thread(target=_emit_success, daemon=True).start()

    status, _duration_ms, _log_path = launcher.run_job(
        env["job"], port=9222, worker_id=0
    )

    assert status == "applied"
    snap = apply_budget.governor().snapshot()
    assert snap.claude_attempts == 1
    assert snap.claude_cost_usd == pytest.approx(0.01)


def test_run_job_applied_via_result_json(run_job_env):
    env = run_job_env
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_inactivity_timeout", 2.0)
    env["monkeypatch"].setitem(env["config"].DEFAULTS, "apply_timeout", 10.0)

    stdout = ControllableStdout()
    _install_fake_popen(env["monkeypatch"], stdout)

    applied_body = (
        ">> browser_click submit-ref Send\n"
        f"{APPLIED_RESULT_JSON}\n"
    )

    def _emit_success() -> None:
        stdout.feed(_assistant_text(applied_body))
        stdout.feed(_result_msg(applied_body))
        stdout.close_feed()

    threading.Thread(target=_emit_success, daemon=True).start()

    status, duration_ms, log_path = launcher.run_job(env["job"], port=9222, worker_id=0)

    assert status == "applied"
    assert log_path is not None
    assert log_path.exists()
    assert duration_ms >= 0
    assert env["killed"] == []
