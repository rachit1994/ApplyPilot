import json
import tempfile
from pathlib import Path

import pytest

from applypilot.apply import gmail_auth
from applypilot.apply.gmail_auth import GmailMessageSummary, search_application_receipt


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        monkeypatch.setenv("APPLYPILOT_DIR", tmp)
        from applypilot import config
        from applypilot import database

        config.load_env()
        monkeypatch.setattr(config, "APP_DIR", Path(tmp))
        database.close_connection()
        yield db
        database.close_connection()


def test_search_application_receipt_matches_company_and_received_copy(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-1",
        date="Tue, 2 Jun 2026 15:47:27 +0000",
        from_="Talent at Linear <no-reply@ashbyhq.com>",
        subject="Thank you for applying to Linear",
        snippet=(
            "We've received your application for the Senior / Staff Product "
            "Engineer, AI role."
        ),
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "Ashby:Linear",
            "title": "Senior / Staff Product Engineer, AI",
            "application_url": "https://jobs.ashbyhq.com/Linear/job/application",
        }
    )

    assert result.confirmed is True
    assert result.message == message


def test_search_application_receipt_rejects_unrelated_recent_email(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-2",
        date="Tue, 2 Jun 2026 15:47:29 +0000",
        from_="Patreon <no-reply@core.patreon.com>",
        subject="Your Patreon login code is F468PD",
        snippet="Copy and paste the code below to log in.",
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "Ashby:Linear",
            "title": "Senior / Staff Product Engineer, AI",
            "application_url": "https://jobs.ashbyhq.com/Linear/job/application",
        }
    )

    assert result.confirmed is False
    assert result.reason == "gmail_receipt_not_found"


def test_search_application_receipt_rejects_title_overlap_wrong_company(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-3",
        date="Sat, 6 Jun 2026 09:28:14 +0000",
        from_="Stripe <no-reply@stripe.com>",
        subject="Your application for our Staff Full Stack Engineer, Identity role at Stripe",
        snippet="Thank you for applying. We've received your application.",
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "WorkableWebSearch:Checkmate",
            "title": "Senior Full Stack Engineer - Python & React JS (India)",
            "application_url": "https://apply.workable.com/itsacheckmate-dot-com/j/EEB66E3358/apply/",
        }
    )

    assert result.confirmed is False
    assert result.reason == "gmail_receipt_not_found"


def test_search_application_receipt_matches_workable_source_slug(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-4",
        date="Sat, 6 Jun 2026 09:46:04 +0000",
        from_="Workable <noreply@candidates.workablemail.com>",
        subject="Thanks for applying to Richpanel",
        snippet=(
            "Richpanel Your application for the Distinguished Full Stack "
            "Engineer job was submitted successfully."
        ),
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "WorkableWebSearch",
            "title": "Distinguished Full Stack Engineer",
            "application_url": "https://apply.workable.com/richpanel-1/j/9C6A60241A/apply/",
        }
    )

    assert result.confirmed is True
    assert result.message == message


def test_search_application_receipt_matches_workable_compact_slug(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-5",
        date="Sat, 6 Jun 2026 09:43:52 +0000",
        from_="Workable <noreply@candidates.workablemail.com>",
        subject="Thanks for applying to Unison Group",
        snippet=(
            "Unison Group Your application for the Senior Front End Developer "
            "job was submitted successfully."
        ),
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "WorkableWebSearch",
            "title": "Senior Front End Developer (Kogito)",
            "application_url": "https://apply.workable.com/unisongroup/j/75BD81990A/apply/",
        }
    )

    assert result.confirmed is True
    assert result.message == message


def test_search_application_receipt_matches_company_tokens(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-6",
        date="Sat, 6 Jun 2026 10:13:22 +0000",
        from_="Workable <noreply@candidates.workablemail.com>",
        subject="Thanks for applying to Mercari, Inc. (India)",
        snippet=(
            "Mercari, Inc. (India) Your application for the Software Engineer, "
            "Fullstack job was submitted successfully."
        ),
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "WorkableWebSearch:Mercari India",
            "title": "Software Engineer, Fullstack",
            "application_url": "https://apply.workable.com/mercari-india/j/DA63859520/apply/",
        }
    )

    assert result.confirmed is True
    assert result.message == message


def test_search_application_receipt_matches_workable_ml_trust_safety_title(monkeypatch):
    message = GmailMessageSummary(
        message_id="msg-7",
        date="Sat, 7 Jun 2026 00:41:00 +0000",
        from_="Workable <noreply@candidates.workablemail.com>",
        subject="Thanks for applying to Mercari, Inc. (India)",
        snippet=(
            "Mercari, Inc. (India) Your application for the Senior Software Engineer - "
            "Machine Learning, Trust and Safety job was submitted successfully."
        ),
    )
    monkeypatch.setattr(gmail_auth, "_search_messages", lambda query, limit: [message])

    result = search_application_receipt(
        {
            "site": "WorkableWebSearch:Mercari India",
            "title": "Senior Software Engineer - Machine Learning, Trust and Safety",
            "application_url": "https://apply.workable.com/mercari-india/j/6E941BF58D/apply/",
        }
    )

    assert result.confirmed is True


def test_job_requires_gmail_receipt_skips_kula(monkeypatch):
    from applypilot.apply import apply_settings

    monkeypatch.delenv("APPLYPILOT_APPLY_TRUST_DIRECT_CONFIRMATION", raising=False)
    job = {
        "url": "https://careers.kula.ai/cashfree/24477/apply/",
        "application_url": "https://careers.kula.ai/cashfree/24477/apply/",
    }
    assert apply_settings.job_on_gmail_optional_host(job) is True
    assert apply_settings.job_requires_gmail_receipt(job) is False


def test_job_requires_gmail_receipt_still_workable(monkeypatch):
    from applypilot.apply import apply_settings

    monkeypatch.delenv("APPLYPILOT_APPLY_TRUST_DIRECT_CONFIRMATION", raising=False)
    job = {
        "url": "https://apply.workable.com/acme/j/ABC123/apply/",
        "application_url": "https://apply.workable.com/acme/j/ABC123/apply/",
    }
    assert apply_settings.job_requires_gmail_receipt(job) is True


def test_reconcile_on_page_submissions_promotes_kula(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.apply.launcher import reconcile_on_page_submissions

    init_db()
    conn = get_connection()
    form = json.dumps({"submitted": True, "fields": []})
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, apply_status, apply_error, apply_form_filled)
        VALUES (?, ?, ?, 'submitted_unverified', 'gmail_receipt_not_found', ?)
        """,
        (
            "https://careers.kula.ai/acme/1/apply/",
            "Engineer",
            "Kula",
            form,
        ),
    )
    conn.commit()

    promoted = reconcile_on_page_submissions()
    assert promoted == 1
    row = conn.execute(
        "SELECT apply_status, verification_confidence FROM jobs WHERE url LIKE '%kula.ai%'"
    ).fetchone()
    assert row["apply_status"] == "applied"
    assert row["verification_confidence"] == "on_page_direct"
