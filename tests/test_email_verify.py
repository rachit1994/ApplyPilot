"""Unit tests for direct/email_verify.py (no live Gmail)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from applypilot.apply.direct import email_verify


def test_infer_code_length_from_maxlength():
    assert email_verify.infer_code_length(maxlength=6) == 6
    assert email_verify.infer_code_length(maxlength="8") == 8


def test_infer_code_length_from_label():
    assert email_verify.infer_code_length(label="Enter the 8-character code") == 8


def test_extract_code_from_text_prefers_length():
    body = "Your verification code is AB12CD34. Ignore XY99."
    assert email_verify.extract_code_from_text(body, code_length=8) == "AB12CD34"


def test_extract_code_from_text_six_char():
    assert email_verify.extract_code_from_text("Code: A1B2C3", code_length=6) == "A1B2C3"


@patch("applypilot.apply.direct.email_verify.gmail_auth.credentials_exist", return_value=True)
@patch("applypilot.apply.direct.email_verify._fetch_message_bodies")
@patch("applypilot.apply.direct.email_verify.gmail_auth._search_messages")
def test_fetch_verification_code_returns_recent(mock_search, mock_bodies, _creds):
    from applypilot.apply import gmail_auth

    summary = gmail_auth.GmailMessageSummary(
        message_id="m1",
        from_="Greenhouse <noreply@greenhouse.io>",
        subject="Your verification code",
        date="Wed, 3 Jun 2026 12:00:00 +0000",
        snippet="Code AB12CD34",
    )
    mock_search.return_value = [summary]
    mock_bodies.return_value = [
        (summary, "Please enter code AB12CD34 to continue.", 1_700_000_000.0),
    ]

    code = email_verify.fetch_verification_code(
        company_hint="Greenhouse",
        since_epoch_s=1_699_999_000.0,
        max_wait_s=1.0,
        poll_s=0.1,
        code_length=8,
    )
    assert code == "AB12CD34"


@patch("applypilot.apply.direct.email_verify.gmail_auth.credentials_exist", return_value=False)
def test_fetch_verification_code_no_credentials(_creds):
    assert (
        email_verify.fetch_verification_code(
            company_hint="x", since_epoch_s=0.0, max_wait_s=0.1, poll_s=0.1
        )
        is None
    )
