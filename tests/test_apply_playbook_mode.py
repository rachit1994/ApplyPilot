"""Mocked apply run uses playbook prompt when APPLYPILOT_APPLY_PROMPT_MODE=playbook."""

from __future__ import annotations

import io
import json
import threading
from unittest.mock import patch

import pytest

from applypilot import config
from applypilot.apply import apply_settings, launcher
from applypilot.apply import prompt as prompt_mod

from test_apply_quota_e2e import (
    ControllableStdout,
    _install_capturing_fake_popen,
    _job_for,
    _minimal_profile,
    quota_e2e_env,
)


def _assistant_text(text: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }
    )


def _result_msg() -> str:
    return json.dumps(
        {
            "type": "result",
            "result": "",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "total_cost_usd": 0.01,
            "num_turns": 2,
        }
    )


@pytest.fixture
def run_job_job(quota_e2e_env: dict) -> dict:
    return _job_for(
        "https://boards.greenhouse.io/acme/jobs/123",
        quota_e2e_env["tmp"],
    )


def test_run_job_playbook_mode_stdin_contains_step_order_not_result_json(
    quota_e2e_env,
    run_job_job: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_MODE", "playbook")
    apply_settings.set_apply_prompt_mode_override(None)
    monkeypatch.setattr(config, "load_profile", lambda: _minimal_profile())
    monkeypatch.setattr(config, "load_search_config", lambda: {})
    monkeypatch.setattr(config, "load_blocked_sso", lambda: [])

    stdout = ControllableStdout()
    fake, captured = _install_capturing_fake_popen(monkeypatch, stdout)
    prompt_capture: list[str] = []

    class CapturingStdin(io.StringIO):
        def write(self, s: str) -> int:
            prompt_capture.append(s)
            return super().write(s)

        def getvalue(self) -> str:
            return "".join(prompt_capture) if prompt_capture else super().getvalue()

    fake.stdin = CapturingStdin()

    def feed_and_close():
        stdout.feed(_assistant_text("RESULT:applied"))
        stdout.feed(_result_msg())
        stdout.close_feed()

    threading.Thread(target=feed_and_close, daemon=True).start()

    with patch.object(launcher, "launch_chrome", return_value=9222):
        status, _ms, _log = launcher.run_job(
            run_job_job,
            port=9222,
            worker_id=0,
            model="haiku",
        )

    stdin_text = fake.stdin.getvalue()  # type: ignore[attr-defined]
    assert "## STEP ORDER" in stdin_text or "STEP ORDER" in stdin_text
    assert "STOP CHECK" in stdin_text
    assert "RESULT_JSON" not in stdin_text
    assert status.startswith("submitted_unverified")


def test_apply_telemetry_includes_prompt_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_PROMPT_MODE", "playbook")
    apply_settings.set_apply_prompt_mode_override(None)
    flags = apply_settings.apply_telemetry_flags()
    assert flags["prompt_mode"] == "playbook"
