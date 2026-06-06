from applypilot.apply import gmail_auth
from applypilot.apply.gmail_auth import GmailMessageSummary, search_application_receipt


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
