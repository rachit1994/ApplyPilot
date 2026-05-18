"""Unit tests for inbox send gates."""

from applypilot.inbox.gates import is_eligible_for_draft, should_skip_reply


def test_skip_not_asked_to_apply():
    thread = {"last_inbound_at": "2026-01-02", "last_outbound_at": None, "reply_status": "pending"}
    opp = {"is_job_related": False, "confidence": 0.9}
    assert should_skip_reply(thread, opp) == "not_asked_to_apply"


def test_skip_outbound_is_latest():
    thread = {
        "last_inbound_at": "2026-01-01T00:00:00+00:00",
        "last_outbound_at": "2026-01-02T00:00:00+00:00",
        "reply_status": "pending",
    }
    opp = {"is_job_related": True, "confidence": 0.9}
    assert should_skip_reply(thread, opp) == "outbound_is_latest"


def test_skip_already_replied():
    thread = {
        "last_inbound_at": "2026-01-02",
        "last_outbound_at": "2026-01-01",
        "reply_status": "sent",
    }
    opp = {"is_job_related": True, "confidence": 0.9}
    assert should_skip_reply(thread, opp) == "already_replied"


def test_eligible_for_send():
    thread = {
        "last_inbound_at": "2026-01-02T00:00:00+00:00",
        "last_outbound_at": "2026-01-01T00:00:00+00:00",
        "reply_status": "drafted",
    }
    opp = {"is_job_related": True, "confidence": 0.85}
    assert should_skip_reply(thread, opp) is None


def test_eligible_for_draft():
    thread = {"reply_status": "pending"}
    opp = {"is_job_related": True, "confidence": 0.8}
    assert is_eligible_for_draft(thread, opp) is True


def test_skip_wrong_intent():
    thread = {"last_inbound_at": "2026-01-02", "reply_status": "pending"}
    opp = {"intent": "rejection", "is_job_related": False, "confidence": 0.95}
    assert should_skip_reply(thread, opp) == "wrong_intent"
