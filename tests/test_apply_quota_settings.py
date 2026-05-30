"""Tests for apply quota controls (model, prompt slim, session reuse)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from applypilot import config
from applypilot.apply import apply_settings, launcher, prompt as prompt_mod


@pytest.fixture
def quota_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLY_WORKER_DIR", tmp_path / "apply-workers")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("APPLYPILOT_APPLY_MODEL", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_PROMPT_SLIM", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_SESSION_REUSE", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_GMAIL_MCP", raising=False)
    return tmp_path


def test_apply_model_defaults_haiku_with_sonnet_fallback(quota_env):
    assert apply_settings.apply_model_default() == "haiku"
    assert apply_settings.apply_model_default("opus") == "opus"
    assert apply_settings.apply_fallback_model() == "sonnet"


def test_env_overrides_apply_model(quota_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_MODEL", "sonnet")
    monkeypatch.setenv("APPLYPILOT_APPLY_SESSION_REUSE", "0")
    assert apply_settings.apply_model_default() == "sonnet"
    assert apply_settings.session_reuse_enabled() is False


def test_build_claude_command_session_reuse(quota_env):
    mcp_path = quota_env / "mcp.json"
    mcp_path.write_text("{}", encoding="utf-8")
    sid = apply_settings.ensure_session_id(0)
    cmd = launcher.build_claude_apply_command(
        model="haiku",
        mcp_config_path=mcp_path,
        worker_id=0,
    )
    assert "--resume" in cmd
    assert sid in cmd
    assert "--session-id" not in cmd
    assert "--no-session-persistence" not in cmd


def test_build_claude_command_fresh_session_omits_session_flags(quota_env):
    """First apply on a worker should not pass a pre-generated --session-id."""
    mcp_path = quota_env / "mcp.json"
    mcp_path.write_text("{}", encoding="utf-8")
    cmd = launcher.build_claude_apply_command(
        model="haiku",
        mcp_config_path=mcp_path,
        worker_id=9,
    )
    assert "--resume" not in cmd
    assert "--session-id" not in cmd
    assert "--no-session-persistence" not in cmd


def test_build_claude_command_no_session_when_disabled(quota_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_SESSION_REUSE", "0")
    mcp_path = quota_env / "mcp.json"
    mcp_path.write_text("{}", encoding="utf-8")
    cmd = launcher.build_claude_apply_command(
        model="haiku",
        mcp_config_path=mcp_path,
        worker_id=1,
    )
    assert "--no-session-persistence" in cmd
    assert "--resume" not in cmd


def test_mcp_config_omits_gmail_when_slim(quota_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_GMAIL_MCP", "0")
    cfg = launcher._make_mcp_config(9222, include_gmail=False)
    assert "playwright" in cfg["mcpServers"]
    assert "gmail" not in cfg["mcpServers"]


def test_should_escalate_to_fallback_for_retriable_failures():
    assert apply_settings.should_escalate_to_fallback(
        "failed:no_result_line",
        primary="haiku",
        fallback="sonnet",
        is_permanent_failure=launcher._is_permanent_failure,
    )
    assert not apply_settings.should_escalate_to_fallback(
        "failed:claude_quota_exhausted:2026-01-01T00:00:00+00:00",
        primary="haiku",
        fallback="sonnet",
        is_permanent_failure=launcher._is_permanent_failure,
    )
    assert not apply_settings.should_escalate_to_fallback(
        "failed:inactivity_timeout",
        primary="haiku",
        fallback="sonnet",
        is_permanent_failure=launcher._is_permanent_failure,
    )


def test_prompt_slim_omits_captcha_for_greenhouse(quota_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_SLIM", "1")
    job = {
        "url": "https://boards.greenhouse.io/acme/jobs/123",
        "application_url": "https://boards.greenhouse.io/acme/jobs/123",
        "title": "Engineer",
        "site": "Acme",
        "tailored_resume_path": str(quota_env / "resume.pdf"),
    }
    (quota_env / "resume.pdf").write_bytes(b"%PDF-1.4\n")
    (quota_env / "resume.txt").write_text("Experience | 2020-2024\nAcme Corp\n", encoding="utf-8")
    monkeypatch.setattr(config, "load_profile", lambda: {
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
    })
    monkeypatch.setattr(config, "load_search_config", lambda: {})
    monkeypatch.setattr(config, "load_blocked_sso", lambda: [])
    text = prompt_mod.build_prompt(job=job, tailored_resume="resume body")
    assert "CAPTCHA DETECT AND SOLVE" not in text
    assert "createTask" not in text


def test_is_stale_session_error():
    assert apply_settings.is_stale_session_error(
        "Error: No conversation found with session ID abc-123"
    )
    assert not apply_settings.is_stale_session_error("applied successfully")


def test_full_form_verify_section_uses_prompt_scripts_module():
    section = prompt_mod._build_form_verify_section()
    assert "emptyRequired" in section
    assert "prompt_scripts" not in section
    assert prompt_mod.prompt_scripts.FORM_VERIFY_JS.split("emptyRequired")[0] in section


def test_parse_and_persist_session_id_from_stream(quota_env):
    msg = {"type": "system", "session_id": "abc-123"}
    assert apply_settings.parse_session_id_from_message(msg) == "abc-123"
    apply_settings.save_session_id(2, "abc-123")
    path = apply_settings.session_store_path(2)
    assert json.loads(path.read_text())["session_id"] == "abc-123"
    apply_settings.clear_session_id(2)
    assert not path.exists()
