"""Tests for template-based referral messages."""

from applypilot.outreach.config import OutreachSettings
from applypilot.outreach.referral_template import render_referral_message


def _settings(template: str) -> OutreachSettings:
    return OutreachSettings(
        enabled=True,
        min_fit_score=7,
        max_job_age_hours=72,
        weekly_connect_target=12,
        max_connects_per_run=5,
        max_messages_per_run=10,
        poll_connected_every_minutes=60,
        skip_if_applied=False,
        require_applied_before_send=True,
        referral_message_template=template,
        openoutreach_base_url="http://127.0.0.1:8741/v1",
        openoutreach_api_key="",
        openoutreach_campaign="test",
        require_gemini_for_draft=False,
        ensure_tailored_resume=False,
        tailor_validation_mode="normal",
        resume_excerpt_chars=1000,
        referral_message_max_words=130,
    )


def test_render_bracket_aliases():
    job = {"title": "Staff Engineer", "recruiter_name": "Alex", "site": "Acme"}
    template = "Hi [Name], targeting the [Job Title] role."
    msg = render_referral_message(job, settings=_settings(template))
    assert "Hi Alex" in msg
    assert "Staff Engineer" in msg


def test_render_fallback_recruiter_name():
    job = {"title": "Backend Dev", "recruiter_name": "", "site": "Co"}
    msg = render_referral_message(job, settings=_settings("Hi {recruiter_name},"))
    assert msg.startswith("Hi there,")


def test_default_template_includes_team_apostrophe():
    job = {"title": "Platform Engineer", "recruiter_name": "Sam", "site": "X"}
    msg = render_referral_message(job, settings=_settings(""))
    assert "team's needs" in msg
    assert "Platform Engineer" in msg
