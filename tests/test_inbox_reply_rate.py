"""Reply-rate instrumentation: intents, job match, report."""

from __future__ import annotations

import json

import pytest

from applypilot.database import get_connection
from applypilot.inbox.intents import (
    INTENT_INTERVIEW_INVITE,
    INTENT_STATUS_UPDATE,
    apply_interview_invite_precision_gate,
    keyword_pre_classify,
)
from applypilot.inbox.job_match import (
    pick_best_job_match,
    record_job_reply,
    score_job_match,
)
from applypilot.inbox.reply_report import build_reply_rate_report
from applypilot.inbox.store import save_gmail_classification, upsert_gmail_message


def test_interview_invite_keyword_precision():
    pre = keyword_pre_classify("Can we schedule a phone screen for next Tuesday?")
    assert pre is not None
    assert pre["intent"] == INTENT_INTERVIEW_INVITE

    intent, conf = apply_interview_invite_precision_gate(
        INTENT_INTERVIEW_INVITE,
        0.8,
        keyword_override=False,
    )
    assert intent == INTENT_STATUS_UPDATE

    intent2, conf2 = apply_interview_invite_precision_gate(
        INTENT_INTERVIEW_INVITE,
        0.8,
        keyword_override=True,
    )
    assert intent2 == INTENT_INTERVIEW_INVITE


def test_score_job_match_company_and_title():
    job = {
        "url": "https://boards.greenhouse.io/acmecorp/jobs/1",
        "title": "Senior Platform Engineer",
        "site": "greenhouse:acmecorp",
        "application_url": "https://boards.greenhouse.io/acmecorp/jobs/1",
    }
    score = score_job_match(
        job,
        companies=["acmecorp"],
        title_hint="Senior Platform Engineer",
        text_blob="acmecorp interview schedule platform engineer",
    )
    assert score >= 0.6


def test_record_job_reply_updates_job():
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, applied_at, apply_status)
        VALUES ('https://example.com/j1', 'Engineer', 'greenhouse:foo', '2026-05-01T00:00:00+00:00', 'applied')
        """
    )
    conn.commit()

    ok = record_job_reply(
        "https://example.com/j1",
        intent="rejection",
        channel="gmail",
        source_id="msg-1",
        received_at="2026-05-02T10:00:00+00:00",
    )
    assert ok is True
    row = conn.execute(
        "SELECT reply_status, reply_channel, reply_source_id FROM jobs WHERE url = ?",
        ("https://example.com/j1",),
    ).fetchone()
    assert row["reply_status"] == "rejection"
    assert row["reply_channel"] == "gmail"
    assert row["reply_source_id"] == "msg-1"


def test_pick_best_job_match_prefers_company():
    conn = get_connection()
    conn.executemany(
        """
        INSERT INTO jobs (url, title, site, applied_at, apply_status)
        VALUES (?, ?, ?, '2026-05-01T00:00:00+00:00', 'applied')
        """,
        [
            ("https://a.com/1", "Backend Engineer", "greenhouse:alphacorp"),
            ("https://b.com/2", "Backend Engineer", "greenhouse:betacorp"),
        ],
    )
    conn.commit()
    jobs = [
        dict(r)
        for r in conn.execute(
            "SELECT url, title, site, application_url, applied_at, apply_status FROM jobs"
        ).fetchall()
    ]
    match = pick_best_job_match(
        jobs,
        companies=["alphacorp"],
        title_hint="Backend Engineer",
        text_blob="alphacorp backend engineer next steps",
    )
    assert match is not None
    assert match["url"] == "https://a.com/1"


def test_reply_rate_report_by_source():
    conn = get_connection()
    conn.executemany(
        """
        INSERT INTO jobs (url, title, site, applied_at, apply_status, reply_at, reply_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "https://a.com/1",
                "Role A",
                "greenhouse:acme",
                "2026-05-20T00:00:00+00:00",
                "applied",
                "2026-05-21T00:00:00+00:00",
                "rejection",
            ),
            (
                "https://a.com/2",
                "Role B",
                "greenhouse:acme",
                "2026-05-19T00:00:00+00:00",
                "submitted_unverified",
                None,
                None,
            ),
            (
                "https://b.com/1",
                "Role C",
                "linkedin",
                "2026-05-18T00:00:00+00:00",
                "applied",
                "2026-05-19T00:00:00+00:00",
                INTENT_INTERVIEW_INVITE,
            ),
        ],
    )
    conn.commit()

    report = build_reply_rate_report(days=30)
    by_name = {r["source"]: r for r in report["sources"]}
    assert by_name["greenhouse:acme"]["applies"] == 2
    assert by_name["greenhouse:acme"]["verified_applies"] == 1
    assert by_name["greenhouse:acme"]["replies"] == 1
    assert by_name["linkedin"]["interview_invites"] == 1
    assert report["totals"]["applies"] == 3
    assert report["totals"]["replies"] == 2


def test_reply_rate_never_exceeds_one_for_unverified_replies():
    """Replies to submitted_unverified applies must not push the rate above 100%."""
    conn = get_connection()
    conn.executemany(
        """
        INSERT INTO jobs (url, title, site, applied_at, apply_status, reply_at, reply_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # 3 submitted-unverified applies that all got a reply, 0 verified.
            (
                f"https://c.com/{i}",
                "Role",
                "cutshort",
                "2026-05-20T00:00:00+00:00",
                "submitted_unverified",
                "2026-05-22T00:00:00+00:00",
                "rejection",
            )
            for i in range(3)
        ],
    )
    conn.commit()

    report = build_reply_rate_report(days=30)
    src = {r["source"]: r for r in report["sources"]}["cutshort"]
    assert src["applies"] == 3
    assert src["verified_applies"] == 0
    assert src["replies"] == 3
    assert src["reply_rate"] == 1.0  # 3/3, not 3/0 → inf and not >1
    assert report["totals"]["reply_rate"] <= 1.0


def test_gmail_store_and_classify_fields():
    upsert_gmail_message(
        message_id="gmsg-1",
        thread_id="t1",
        from_address="recruiter@acmecorp.com",
        subject="Interview availability",
        snippet="Please book a phone screen slot",
        received_at="2026-05-10T12:00:00+00:00",
    )
    save_gmail_classification(
        "gmsg-1",
        intent=INTENT_INTERVIEW_INVITE,
        intent_confidence=0.93,
        extracted_title="Engineer",
        extracted_company="Acme Corp",
        reasoning="keyword:interview_invite",
    )
    row = get_connection().execute(
        "SELECT intent, extracted_company FROM inbox_gmail_messages WHERE message_id = ?",
        ("gmsg-1",),
    ).fetchone()
    assert row["intent"] == INTENT_INTERVIEW_INVITE
    assert row["extracted_company"] == "Acme Corp"


def test_auto_ack_and_other_are_not_human_replies():
    from applypilot.inbox.intents import (
        INTENT_AUTO_ACK,
        INTENT_OTHER,
        INTENT_REJECTION,
        is_human_reply_intent,
        looks_like_auto_acknowledgement,
    )

    # "other" (catch-all) and auto-acks must not count as recruiter replies.
    assert is_human_reply_intent(INTENT_OTHER) is False
    assert is_human_reply_intent(INTENT_AUTO_ACK) is False
    assert is_human_reply_intent(INTENT_REJECTION) is True

    assert looks_like_auto_acknowledgement("Thank you for applying to Acme.")
    assert looks_like_auto_acknowledgement("We have received your application.")
    # A real next step beats the boilerplate "thank you for applying".
    assert not looks_like_auto_acknowledgement(
        "Thanks for applying — can we schedule a phone screen?"
    )
    assert not looks_like_auto_acknowledgement("Are you available next week?")


def test_gmail_classify_overrides_ats_auto_ack(monkeypatch):
    """An ATS auto-ack the LLM calls apply_request is downgraded to auto_ack."""
    from applypilot.inbox import gmail_scanner
    from applypilot.inbox.intents import INTENT_AUTO_ACK

    upsert_gmail_message(
        message_id="ack-1",
        thread_id=None,
        from_address="no-reply@greenhouse.io",
        subject="Thank you for applying to Acme",
        snippet="We have received your application and will review it shortly.",
        received_at="2026-05-10T12:00:00+00:00",
    )
    monkeypatch.setattr(
        gmail_scanner,
        "classify_message",
        lambda text, **kw: {
            "intent": "apply_request",
            "confidence": 0.9,
            "intent_confidence": 0.9,
            "extracted_title": None,
            "extracted_company": "Acme",
            "reasoning": "looked like an apply ask",
        },
    )

    result = gmail_scanner.classify_gmail_messages()
    assert result["classified"] == 1
    assert result["human_replies"] == 0

    row = get_connection().execute(
        "SELECT intent FROM inbox_gmail_messages WHERE message_id = ?", ("ack-1",)
    ).fetchone()
    assert row["intent"] == INTENT_AUTO_ACK


def test_gmail_header_date_normalized_to_iso():
    from applypilot.inbox.gmail_scanner import _header_date_to_iso

    # RFC 2822 header with a non-UTC offset -> ISO 8601 UTC, comparable to cutoffs.
    iso = _header_date_to_iso("Wed, 03 Jun 2026 14:23:01 +0530")
    assert iso == "2026-06-03T08:53:01+00:00"
    # A stored Gmail reply_at must sort against ISO cutoffs lexicographically.
    assert iso < "2026-06-04T00:00:00+00:00"
    assert iso >= "2026-05-27T00:00:00+00:00"
    assert _header_date_to_iso("") is None
    assert _header_date_to_iso("not-a-date") is None


def test_classify_message_interview_gate(monkeypatch):
    class FakeClient:
        def chat(self, **kwargs):
            return json.dumps(
                {
                    "intent": "interview_invite",
                    "confidence": 0.85,
                    "extracted_title": None,
                    "extracted_company": None,
                    "reasoning": "LLM guess.",
                }
            )

    from applypilot.inbox.classifier import classify_message

    result = classify_message(
        "We would like to move forward.",
        client=FakeClient(),
        threshold=0.7,
    )
    assert result["intent"] != INTENT_INTERVIEW_INVITE
