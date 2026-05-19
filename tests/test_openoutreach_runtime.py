"""Tests for OpenOutreach runtime helpers."""

from pathlib import Path
from unittest.mock import patch

from applypilot.outreach.config import OutreachSettings
from applypilot.outreach import openoutreach_runtime as rt


def test_find_openoutreach_root_env(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    with patch.dict("os.environ", {"OPENOUTREACH_ROOT": str(tmp_path)}):
        assert rt.find_openoutreach_root() == tmp_path.resolve()


def test_build_openoutreach_env_sets_api_key() -> None:
    settings = OutreachSettings(
        enabled=True,
        min_fit_score=7,
        max_job_age_hours=72,
        weekly_connect_target=12,
        max_connects_per_run=5,
        max_messages_per_run=10,
        poll_connected_every_minutes=60,
        skip_if_applied=False,
        openoutreach_base_url="http://127.0.0.1:8741/v1",
        openoutreach_api_key="secret-from-applypilot",
        openoutreach_campaign="test",
        require_gemini_for_draft=True,
        ensure_tailored_resume=True,
        tailor_validation_mode="normal",
        resume_excerpt_chars=1000,
        referral_message_max_words=100,
    )
    with patch.dict("os.environ", {}, clear=False):
        env = rt.build_openoutreach_env(settings)
    assert env["OPENOUTREACH_API_KEY"] == "secret-from-applypilot"


def test_parse_base_url_port() -> None:
    host, port = rt.parse_base_url_port("http://127.0.0.1:8741/v1")
    assert host == "127.0.0.1"
    assert port == 8741
