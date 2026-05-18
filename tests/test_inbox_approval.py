"""Explicit approval gate before live send."""

from pathlib import Path

import applypilot.config as ap_config
import applypilot.database as ap_database
from applypilot.database import close_connection, get_connection, init_db
from applypilot.inbox.store import approve_threads, list_send_candidates, save_classification, save_draft


def _init_test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    ap_config.APP_DIR = Path(tmp_path)
    ap_config.DB_PATH = ap_config.APP_DIR / "applypilot.db"
    ap_database.DB_PATH = ap_config.DB_PATH
    close_connection()
    return init_db(ap_config.DB_PATH)


def _seed_thread(urn: str, public_id: str) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO inbox_threads (conversation_urn, participant_public_id, folder)
        VALUES (?, ?, 'other')
        """,
        (urn, public_id),
    )
    conn.execute(
        "INSERT INTO inbox_replies (conversation_urn, reply_status) VALUES (?, 'pending')",
        (urn,),
    )
    conn.commit()


def test_list_send_candidates_approved_only(tmp_path, monkeypatch):
    _init_test_db(tmp_path, monkeypatch)
    urn = "urn:li:msg:thread:approval-test"
    _seed_thread(urn, "bob")
    save_classification(
        urn,
        is_job_related=True,
        confidence=0.9,
        extracted_title="Engineer",
        extracted_company="Acme",
        reasoning="apply",
        intent="apply_request",
    )
    save_draft(urn, "Hello", "fixed")

    assert len(list_send_candidates(10, approved_only=False)) == 1
    assert len(list_send_candidates(10, approved_only=True)) == 0

    approve_threads(["bob"])
    assert len(list_send_candidates(10, approved_only=True)) == 1
