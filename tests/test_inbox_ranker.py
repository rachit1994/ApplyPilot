"""Ranked inbox queue ordering."""

from applypilot.inbox.gates import should_skip_reply
from applypilot.inbox.ranker import (
    build_ranked_queue,
    composite_fit_score,
    confidence_to_fit_score,
)


def test_confidence_to_fit_score():
    assert confidence_to_fit_score(0.95) == 10
    assert confidence_to_fit_score(0.74) == 7
    assert confidence_to_fit_score(0) == 0


def test_composite_fit_score_ats_beats_confidence_only():
    low, _ = composite_fit_score(confidence=0.95, apply_url=None, extracted_title=None, extracted_company=None)
    high, breakdown = composite_fit_score(
        confidence=0.75,
        apply_url="https://jobs.lever.co/co/role",
        extracted_title="Engineer",
        extracted_company="Acme",
    )
    assert high > low
    assert breakdown["ats_pts"] == 2


def test_build_ranked_queue_orders_by_fit_score(monkeypatch):
    threads = [
        {
            "conversation_urn": "urn:a",
            "participant_public_id": "low",
            "folder": "other",
            "is_job_related": 1,
            "intent": "apply_request",
            "confidence": 0.75,
            "reasoning": "apply",
            "last_inbound_at": "2026-05-10",
            "last_outbound_at": None,
            "reply_status": "pending",
            "latest_inbound_text": "please apply",
        },
        {
            "conversation_urn": "urn:b",
            "participant_public_id": "high",
            "folder": "other",
            "is_job_related": 1,
            "intent": "apply_request",
            "confidence": 0.75,
            "apply_url": "https://boards.greenhouse.io/x/y",
            "ats_vendor": "greenhouse",
            "extracted_title": "SWE",
            "extracted_company": "Co",
            "reasoning": "apply now",
            "last_inbound_at": "2026-05-09",
            "last_outbound_at": None,
            "reply_status": "pending",
            "latest_inbound_text": "apply here",
        },
        {
            "conversation_urn": "urn:c",
            "participant_public_id": "skip",
            "folder": "other",
            "is_job_related": 0,
            "intent": "spam",
            "confidence": 0.9,
            "reasoning": "nope",
            "last_inbound_at": "2026-05-11",
            "latest_inbound_text": "webinar",
        },
    ]

    monkeypatch.setattr(
        "applypilot.inbox.ranker.list_eligible_other_threads",
        lambda **kwargs: [t for t in threads if t.get("intent") == "apply_request"],
    )

    rows = build_ranked_queue(limit=10, require_unanswered=True)
    assert len(rows) == 2
    assert rows[0]["participant_public_id"] == "high"
    assert rows[0]["rank"] == 1
    assert rows[0]["fit_score"] > rows[1]["fit_score"]
    assert rows[0]["eligible_to_send"] is True


def test_outbound_latest_not_eligible():
    thread = {
        "last_inbound_at": "2026-01-01",
        "last_outbound_at": "2026-01-02",
        "reply_status": "pending",
    }
    opp = {"is_job_related": True, "confidence": 0.9}
    assert should_skip_reply(thread, opp) == "outbound_is_latest"
