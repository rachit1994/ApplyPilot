"""Connect eligibility respects require_applied_before_send."""

from datetime import datetime, timezone

from applypilot.database import get_connection
from applypilot.outreach.config import OutreachSettings
from applypilot.outreach.orchestrator import _eligible_connect_rows


def _settings(**kwargs) -> OutreachSettings:
    base = dict(
        enabled=True,
        min_fit_score=7,
        max_job_age_hours=72,
        weekly_connect_target=12,
        max_connects_per_run=5,
        max_messages_per_run=10,
        poll_connected_every_minutes=60,
        skip_if_applied=False,
        require_applied_before_send=True,
        referral_message_template="Hi {recruiter_name}",
        openoutreach_base_url="http://127.0.0.1:8741/v1",
        openoutreach_api_key="x",
        openoutreach_campaign="test",
        require_gemini_for_draft=False,
        ensure_tailored_resume=False,
        tailor_validation_mode="normal",
        resume_excerpt_chars=1000,
        referral_message_max_words=130,
    )
    base.update(kwargs)
    return OutreachSettings(**base)


def test_connect_requires_applied_at():
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, discovered_at,
            recruiter_public_id, referral_message, referral_status, applied_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://linkedin.com/jobs/1",
            "Eng",
            "linkedin",
            8,
            now,
            "recruiter1",
            "hello",
            "pending_connect",
            None,
        ),
    )
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, discovered_at,
            recruiter_public_id, referral_message, referral_status, applied_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://linkedin.com/jobs/2",
            "Eng2",
            "linkedin",
            8,
            now,
            "recruiter2",
            "hello",
            "pending_connect",
            now,
        ),
    )
    conn.commit()
    settings = _settings()
    rows = _eligible_connect_rows(conn, settings)
    assert len(rows) == 1
    assert rows[0]["url"].endswith("/2")
