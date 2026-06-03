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
