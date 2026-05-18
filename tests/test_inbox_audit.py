"""Inbox audit log persistence."""

from pathlib import Path

import applypilot.config as ap_config
import applypilot.database as ap_database
from applypilot.database import close_connection, get_connection, init_db
from applypilot.inbox.audit import list_audit_events, log_event


def test_log_and_list_audit_events(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    ap_config.APP_DIR = Path(tmp_path)
    ap_config.DB_PATH = ap_config.APP_DIR / "applypilot.db"
    ap_database.DB_PATH = ap_config.DB_PATH
    close_connection()
    init_db(ap_config.DB_PATH)

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

    events = list_audit_events(limit=10, participant_public_id="alice")
    assert len(events) >= 2
    assert events[0]["event_type"] in ("classified", "gated")
    assert events[0]["payload"]
