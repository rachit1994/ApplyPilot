"""End-to-end checks for apply quota improvements (model, prompt, session, telemetry).

These tests simulate the apply pipeline without calling the real Claude API.
They assert measurable wins (smaller prompts, cheaper defaults) and correct wiring
(haiku argv, session --resume, Sonnet fallback, DB telemetry).
"""

from __future__ import annotations

import io
import json
import queue
import threading
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from applypilot import config
from applypilot.apply import apply_settings, launcher
from applypilot.apply import prompt as prompt_mod

APPLIED_RESULT_JSON = (
    'RESULT_JSON:{"status":"applied","submit_click_ref":"submit-ref",'
    '"submit_button_text":"Send","pre_submit_url":"https://jobs.example/apply",'
    '"post_submit_url":"https://jobs.example/thanks",'
    '"post_submit_snapshot":{"fieldCount":0,"fields":[]},'
    '"confirmation_copy":"Application received"}'
)


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


class ControllableStdout:
    """Blocking stdout stand-in for fake Claude stream-json."""

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

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


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

MIN_GREENHOUSE_PROMPT_SAVINGS_RATIO = 0.12  # slim must shed >=12% vs legacy full
MIN_WORKDAY_SLIM_VS_FULL_SAVINGS = 0.05  # workday keeps slim captcha block


def _minimal_profile() -> dict:
    return {
        "personal": {
            "full_name": "Test User",
            "email": "test@example.com",
            "phone": "+1 555 0100",
            "city": "Bangalore",
            "password": "secret",
        },
        "work_authorization": {
            "legally_authorized_to_work": "Yes",
            "require_sponsorship": "No",
        },
        "compensation": {"salary_expectation": "4000000", "salary_currency": "INR"},
        "experience": {"target_roles": ["Engineer"]},
        "availability": {"earliest_start_date": "Immediately"},
        "eeo_voluntary": {},
    }


def _job_for(url: str, base: Path) -> dict:
    pdf = base / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = pdf.with_suffix(".txt")
    txt.write_text("Experience | 2020-2024\nAcme Corp\n", encoding="utf-8")
    return {
        "url": url,
        "application_url": url,
        "title": "Engineer",
        "site": "Acme",
        "tailored_resume_path": str(pdf),
        "fit_score": 9,
    }


def _build_prompt_with_slim(
    job: dict,
    *,
    slim: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_SLIM", "1" if slim else "0")
    monkeypatch.setattr(config, "load_profile", lambda: _minimal_profile())
    monkeypatch.setattr(config, "load_search_config", lambda: {})
    monkeypatch.setattr(config, "load_blocked_sso", lambda: [])
    return prompt_mod.build_prompt(job=job, tailored_resume="resume body")


@pytest.fixture
def quota_e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated dirs + DB + dashboard stubs for quota E2E."""
    from applypilot import database
    from applypilot.apply import dashboard

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLY_WORKER_DIR", tmp_path / "apply-workers")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    database.close_connection(db_path)
    database.init_db(db_path)

    worker_dir = tmp_path / "worker-0"
    worker_dir.mkdir(parents=True, exist_ok=True)

    def fake_ensure_resume_pdf(path: str | Path) -> Path:
        pdf = Path(path)
        if pdf.suffix.lower() != ".pdf":
            pdf = pdf.with_suffix(".pdf")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        if not pdf.exists():
            pdf.write_bytes(b"%PDF-1.4\n")
        return pdf.resolve()

    monkeypatch.setattr(prompt_mod, "ensure_resume_pdf", fake_ensure_resume_pdf)
    monkeypatch.setattr(launcher, "reset_worker_dir", lambda _wid: worker_dir)
    monkeypatch.setattr(launcher, "_kill_process_tree", lambda _pid: None)
    monkeypatch.setattr(dashboard, "init_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "update_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "add_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "get_state", lambda *args, **kwargs: None)

    for key in (
        "APPLYPILOT_APPLY_MODEL",
        "APPLYPILOT_APPLY_FALLBACK_MODEL",
        "APPLYPILOT_APPLY_PROMPT_SLIM",
        "APPLYPILOT_APPLY_SESSION_REUSE",
        "APPLYPILOT_APPLY_GMAIL_MCP",
    ):
        monkeypatch.delenv(key, raising=False)

    return {
        "tmp": tmp_path,
        "db_path": db_path,
        "worker_dir": worker_dir,
        "monkeypatch": monkeypatch,
    }


@pytest.fixture
def run_job_job(quota_e2e_env: dict) -> dict:
    return _job_for(
        "https://boards.greenhouse.io/acme/jobs/123",
        quota_e2e_env["tmp"],
    )


# ---------------------------------------------------------------------------
# Measurable improvements (prompt + MCP payload)
# ---------------------------------------------------------------------------


def test_improvement_greenhouse_prompt_is_smaller_without_capsolver_api(
    quota_e2e_env, monkeypatch: pytest.MonkeyPatch
):
    """Greenhouse + slim: drop heavy CapSolver JS; measurable token savings."""
    job = _job_for(
        "https://boards.greenhouse.io/acme/jobs/123",
        quota_e2e_env["tmp"],
    )
    full = _build_prompt_with_slim(job, slim=False, monkeypatch=monkeypatch)
    slim_text = _build_prompt_with_slim(job, slim=True, monkeypatch=monkeypatch)

    assert "createTask" in full
    assert "CAPTCHA DETECT" in full
    assert "createTask" not in slim_text
    assert "CAPTCHA DETECT" not in slim_text

    savings = 1.0 - (len(slim_text) / len(full))
    assert savings >= MIN_GREENHOUSE_PROMPT_SAVINGS_RATIO, (
        f"expected >= {MIN_GREENHOUSE_PROMPT_SAVINGS_RATIO:.0%} prompt reduction, "
        f"got {savings:.1%} (full={len(full)}, slim={len(slim_text)})"
    )


def test_improvement_workday_uses_slim_captcha_not_full_api(
    quota_e2e_env, monkeypatch: pytest.MonkeyPatch
):
    """Workday still gets captcha guidance when slim, but drops the full detect/solve JS cookbook."""
    job = _job_for(
        "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123",
        quota_e2e_env["tmp"],
    )
    full = _build_prompt_with_slim(job, slim=False, monkeypatch=monkeypatch)
    slim_text = _build_prompt_with_slim(job, slim=True, monkeypatch=monkeypatch)

    assert "--- CAPTCHA DETECT ---" in full
    assert "--- CAPTCHA DETECT ---" not in slim_text
    assert "CAPTCHA (only when visible)" in slim_text

    assert len(slim_text) < len(full)
    savings = 1.0 - (len(slim_text) / len(full))
    assert savings >= MIN_WORKDAY_SLIM_VS_FULL_SAVINGS


def test_improvement_mcp_config_omits_gmail_for_generic_job_when_slim(
    quota_e2e_env, monkeypatch: pytest.MonkeyPatch
):
    """Non-ATS, non-LinkedIn URLs skip Gmail MCP when slim + APPLYPILOT_APPLY_GMAIL_MCP=0."""
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_SLIM", "1")
    monkeypatch.setenv("APPLYPILOT_APPLY_GMAIL_MCP", "0")
    job = _job_for(
        "https://jobs.example.com/careers/engineer-123",
        quota_e2e_env["tmp"],
    )
    assert apply_settings.job_likely_needs_gmail(job) is False

    slim_cfg = launcher._make_mcp_config(9222, include_gmail=False)
    full_cfg = launcher._make_mcp_config(9222, include_gmail=True)

    assert "gmail" not in slim_cfg["mcpServers"]
    assert "gmail" in full_cfg["mcpServers"]
    slim_bytes = len(json.dumps(slim_cfg))
    full_bytes = len(json.dumps(full_cfg))
    assert slim_bytes < full_bytes


def test_improvement_greenhouse_keeps_gmail_mcp_but_slimmer_email_prompt(
    quota_e2e_env, monkeypatch: pytest.MonkeyPatch
):
    """Greenhouse still loads Gmail MCP (verification-heavy ATS) but email instructions are shorter."""
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_SLIM", "1")
    job = _job_for(
        "https://boards.greenhouse.io/acme/jobs/123",
        quota_e2e_env["tmp"],
    )
    assert apply_settings.job_likely_needs_gmail(job) is True

    full = _build_prompt_with_slim(job, slim=False, monkeypatch=monkeypatch)
    slim_text = _build_prompt_with_slim(job, slim=True, monkeypatch=monkeypatch)

    assert "mcp__gmail__search_emails" in full
    assert "mcp__gmail__search_emails" in slim_text
    assert "== EMAIL VERIFICATION ==" in slim_text
    assert len(slim_text) < len(full)


def test_improvement_linkedin_job_keeps_gmail_mcp_when_slim(
    quota_e2e_env, monkeypatch: pytest.MonkeyPatch
):
    """LinkedIn postings may redirect to ATS; keep Gmail MCP until host is known."""
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_SLIM", "1")
    monkeypatch.setenv("APPLYPILOT_APPLY_GMAIL_MCP", "0")
    job = _job_for(
        "https://in.linkedin.com/jobs/view/senior-engineer-at-acme-123",
        quota_e2e_env["tmp"],
    )
    job["site"] = "LinkedIn"
    assert apply_settings.job_likely_needs_gmail(job) is True


def test_improvement_defaults_use_haiku_not_sonnet(quota_e2e_env):
    """Config + settings defaults match the quota plan (haiku primary, sonnet fallback)."""
    assert config.DEFAULTS["apply_model_default"] == "haiku"
    assert config.DEFAULTS["apply_fallback_model"] == "sonnet"
    assert config.DEFAULTS["apply_prompt_slim_enabled"] is True
    assert config.DEFAULTS["apply_session_reuse_enabled"] is True
    assert apply_settings.apply_model_default() == "haiku"
    assert apply_settings.apply_fallback_model() == "sonnet"


# ---------------------------------------------------------------------------
# E2E: run_job wiring (fake Claude subprocess)
# ---------------------------------------------------------------------------


def _emit_applied_success(stdout: ControllableStdout, *, session_id: str | None = None) -> None:
    body = f">> browser_click submit-ref Send\n{APPLIED_RESULT_JSON}\n"
    if session_id:
        stdout.feed(
            json.dumps({"type": "system", "session_id": session_id})
        )
    stdout.feed(_assistant_text(body))
    stdout.feed(_result_msg(body))
    stdout.close_feed()


def test_e2e_run_job_invokes_haiku_with_session_reuse_not_no_persistence(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    env = quota_e2e_env
    mp = env["monkeypatch"]
    mp.setitem(config.DEFAULTS, "apply_inactivity_timeout", 2.0)
    mp.setitem(config.DEFAULTS, "apply_timeout", 10.0)

    stdout = ControllableStdout()
    _fake, captured = _install_capturing_fake_popen(mp, stdout)

    def _go() -> None:
        _emit_applied_success(stdout, session_id="session-from-stream-abc")

    threading.Thread(target=_go, daemon=True).start()

    status, _duration_ms, _log_path = launcher.run_job(
        run_job_job,
        port=9222,
        worker_id=0,
        model="haiku",
    )

    assert status == "applied"
    cmd: list[str] = captured["args"][0]
    assert "haiku" in cmd
    assert "sonnet" not in cmd
    assert "--no-session-persistence" not in cmd
    assert "--session-id" not in cmd
    assert "--resume" not in cmd
    assert apply_settings.load_session_id(0) == "session-from-stream-abc"


def test_e2e_second_job_reuses_persisted_session_id(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    """Second apply on the same worker should pass --resume <stored id>."""
    env = quota_e2e_env
    mp = env["monkeypatch"]
    mp.setitem(config.DEFAULTS, "apply_inactivity_timeout", 2.0)
    mp.setitem(config.DEFAULTS, "apply_timeout", 10.0)

    apply_settings.save_session_id(0, "worker-session-xyz")

    stdout = ControllableStdout()
    _fake, captured = _install_capturing_fake_popen(mp, stdout)

    def _go() -> None:
        _emit_applied_success(stdout)

    threading.Thread(target=_go, daemon=True).start()

    launcher.run_job(run_job_job, port=9222, worker_id=0, model="haiku")

    cmd: list[str] = captured["args"][0]
    assert "--resume" in cmd
    resume_idx = cmd.index("--resume")
    assert cmd[resume_idx + 1] == "worker-session-xyz"
    assert "--no-session-persistence" not in cmd


def test_e2e_run_job_writes_mcp_without_gmail_for_generic_job(
    quota_e2e_env, monkeypatch: pytest.MonkeyPatch
):
    mp = quota_e2e_env["monkeypatch"]
    mp.setenv("APPLYPILOT_APPLY_GMAIL_MCP", "0")
    mp.setitem(config.DEFAULTS, "apply_inactivity_timeout", 2.0)
    mp.setitem(config.DEFAULTS, "apply_timeout", 10.0)

    job = _job_for(
        "https://jobs.example.com/careers/engineer-123",
        quota_e2e_env["tmp"],
    )

    stdout = ControllableStdout()
    _install_fake_popen(mp, stdout)

    def _go() -> None:
        _emit_applied_success(stdout)

    threading.Thread(target=_go, daemon=True).start()
    launcher.run_job(job, port=9222, worker_id=0, model="haiku")

    mcp_path = config.APP_DIR / ".mcp-apply-0.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "playwright" in mcp["mcpServers"]
    assert "gmail" not in mcp["mcpServers"]


def test_e2e_stale_session_retries_once_after_clearing_persisted_id(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    apply_settings.save_session_id(0, "stale-session")
    calls: list[str] = []

    def fake_run_job(job, *, port, worker_id, model, dry_run, pace_seconds, confirm_submit):
        calls.append(model)
        if len(calls) == 1:
            return "failed:claude_stale_session", 50, None
        return "applied", 200, Path("/tmp/fake.log")

    mp = quota_e2e_env["monkeypatch"]
    with patch.object(launcher, "run_job", side_effect=fake_run_job):
        result, duration_ms, _log = launcher._run_job_with_optional_fallback(
            run_job_job,
            port=9222,
            worker_id=0,
            primary_model="haiku",
            dry_run=False,
            pace_seconds=0.0,
            confirm_submit=False,
        )

    assert calls == ["haiku", "haiku"]
    assert result == "applied"
    assert duration_ms == 200
    assert apply_settings.load_session_id(0) is None


def test_e2e_stale_session_fast_fail_clears_persisted_session(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    mp = quota_e2e_env["monkeypatch"]
    mp.setitem(config.DEFAULTS, "apply_inactivity_timeout", 5.0)
    mp.setitem(config.DEFAULTS, "apply_timeout", 30.0)
    apply_settings.save_session_id(0, "stale-session")

    stdout = ControllableStdout()

    def _emit_stale() -> None:
        stdout.feed(
            _assistant_text("No conversation found with session ID stale-session")
        )

    _install_fake_popen(mp, stdout)
    threading.Thread(target=_emit_stale, daemon=True).start()

    status, _duration_ms, _log_path = launcher.run_job(
        run_job_job, port=9222, worker_id=0, model="haiku"
    )

    assert status == "failed:claude_stale_session"
    assert apply_settings.load_session_id(0) is None


def test_e2e_quota_fast_fail_clears_persisted_session(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    mp = quota_e2e_env["monkeypatch"]
    mp.setitem(config.DEFAULTS, "apply_inactivity_timeout", 5.0)
    mp.setitem(config.DEFAULTS, "apply_timeout", 30.0)
    apply_settings.save_session_id(0, "stale-session")

    stdout = ControllableStdout()

    def _emit_quota() -> None:
        stdout.feed(
            _assistant_text("You've hit your limit · resets 11am (Asia/Calcutta)")
        )

    _install_fake_popen(mp, stdout)
    threading.Thread(target=_emit_quota, daemon=True).start()

    status, _duration_ms, _log_path = launcher.run_job(
        run_job_job, port=9222, worker_id=0, model="haiku"
    )

    assert status.startswith("failed:claude_quota_exhausted:")
    assert apply_settings.load_session_id(0) is None


# ---------------------------------------------------------------------------
# E2E: fallback + telemetry
# ---------------------------------------------------------------------------


def test_e2e_fallback_retries_on_sonnet_after_retriable_haiku_failure(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    calls: list[str] = []

    def fake_run_job(job, *, port, worker_id, model, dry_run, pace_seconds, confirm_submit):
        calls.append(model)
        if model == "haiku":
            return "failed:no_result_line", 100, None
        return "applied", 200, Path("/tmp/fake.log")

    mp = quota_e2e_env["monkeypatch"]
    with patch.object(launcher, "run_job", side_effect=fake_run_job):
        result, duration_ms, _log = launcher._run_job_with_optional_fallback(
            run_job_job,
            port=9222,
            worker_id=0,
            primary_model="haiku",
            dry_run=False,
            pace_seconds=0.0,
            confirm_submit=False,
        )

    assert calls == ["haiku", "sonnet"]
    assert result == "applied"
    assert duration_ms == 200


def test_e2e_fallback_skipped_on_quota_failure(quota_e2e_env, run_job_job):
    calls: list[str] = []

    def fake_run_job(job, *, port, worker_id, model, dry_run, pace_seconds, confirm_submit):
        calls.append(model)
        return "failed:claude_quota_exhausted:2026-05-28T12:00:00+00:00", 50, None

    with patch.object(launcher, "run_job", side_effect=fake_run_job):
        result, _duration_ms, _log = launcher._run_job_with_optional_fallback(
            run_job_job,
            port=9222,
            worker_id=0,
            primary_model="haiku",
            dry_run=False,
            pace_seconds=0.0,
            confirm_submit=False,
        )

    assert calls == ["haiku"]
    assert result.startswith("failed:claude_quota_exhausted:")


def test_e2e_success_records_quota_telemetry_in_db(
    quota_e2e_env, run_job_job, monkeypatch: pytest.MonkeyPatch
):
    from applypilot import database

    mp = quota_e2e_env["monkeypatch"]
    mp.setitem(config.DEFAULTS, "apply_inactivity_timeout", 2.0)
    mp.setitem(config.DEFAULTS, "apply_timeout", 10.0)

    stdout = ControllableStdout()
    _install_fake_popen(mp, stdout)

    def _go() -> None:
        _emit_applied_success(stdout)

    threading.Thread(target=_go, daemon=True).start()

    status, _duration_ms, _log_path = launcher.run_job(
        run_job_job, port=9222, worker_id=0, model="haiku"
    )
    assert status == "applied"

    conn = database.get_connection(quota_e2e_env["db_path"])
    row = conn.execute(
        """
        SELECT model, operation, metadata_json, cache_read_tokens
        FROM llm_usage_events
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    assert row["model"] == "haiku"
    assert row["operation"] == "apply"
    meta: dict[str, Any] = json.loads(row["metadata_json"])
    assert meta["model_used"] == "haiku"
    assert meta["prompt_slim"] is True
    assert meta["session_reuse"] is True
    assert meta["apply_model_default"] == "haiku"
    assert meta["apply_fallback_model"] == "sonnet"
    assert meta["job_url"] == run_job_job["url"]


def test_e2e_improvement_report_snapshot(quota_e2e_env, monkeypatch: pytest.MonkeyPatch):
    """Single test documents measured deltas for CI logs (prompt + MCP bytes)."""
    gh = _job_for("https://boards.greenhouse.io/acme/jobs/1", quota_e2e_env["tmp"])
    wd = _job_for(
        "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/2",
        quota_e2e_env["tmp"],
    )
    gh_full = _build_prompt_with_slim(gh, slim=False, monkeypatch=monkeypatch)
    gh_slim = _build_prompt_with_slim(gh, slim=True, monkeypatch=monkeypatch)
    wd_full = _build_prompt_with_slim(wd, slim=False, monkeypatch=monkeypatch)
    wd_slim = _build_prompt_with_slim(wd, slim=True, monkeypatch=monkeypatch)

    gh_savings = round(100 * (1 - len(gh_slim) / len(gh_full)), 1)
    wd_savings = round(100 * (1 - len(wd_slim) / len(wd_full)), 1)
    mcp_slim = len(json.dumps(launcher._make_mcp_config(9222, include_gmail=False)))
    mcp_full = len(json.dumps(launcher._make_mcp_config(9222, include_gmail=True)))

    report = {
        "greenhouse_prompt_chars_full": len(gh_full),
        "greenhouse_prompt_chars_slim": len(gh_slim),
        "greenhouse_prompt_savings_percent": gh_savings,
        "workday_prompt_chars_full": len(wd_full),
        "workday_prompt_chars_slim": len(wd_slim),
        "workday_prompt_savings_percent": wd_savings,
        "mcp_config_bytes_without_gmail": mcp_slim,
        "mcp_config_bytes_with_gmail": mcp_full,
        "default_model": apply_settings.apply_model_default(),
        "fallback_model": apply_settings.apply_fallback_model(),
    }
    # Sanity: improvements are non-trivial
    assert gh_savings >= MIN_GREENHOUSE_PROMPT_SAVINGS_RATIO * 100
    assert mcp_slim < mcp_full
    assert report["default_model"] == "haiku"
    # Visible in pytest -vv failure output if assertions above fail
    assert isinstance(report, dict)
