"""Inbox audit log persistence."""

from pathlib import Path

import applypilot.config as ap_config
from applypilot.database import close_connection, get_connection, init_db
from applypilot.inbox.audit import list_audit_events, log_event


def test_log_and_list_audit_events(tmp_path, monkeypatch, isolated_db):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    ap_config.APP_DIR = Path(tmp_path)
    close_connection()
    init_db()

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO inbox_threads (conversation_urn, participant_public_id, folder)
        VALUES ('urn:li:msg:thread:audit-test', 'alice', 'other')
        """
    )
    conn.commit()

    log_event("urn:li:msg:thread:audit-test", "classified", {"intent": "apply_request", "confidence": 0.9})
    log_event("urn:li:msg:thread:audit-test", "gated", {"skip_reason": "outbound_is_latest"})

    events = list_audit_events(conversation_urn="urn:li:msg:thread:audit-test")
    assert len(events) == 2
    assert events[0]["event_type"] == "gated"
    assert events[1]["event_type"] == "classified"
