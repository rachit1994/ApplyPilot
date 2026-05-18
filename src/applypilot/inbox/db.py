"""SQLite schema for LinkedIn inbox job-reply lifecycle (independent from jobs table)."""

from __future__ import annotations

import sqlite3

INBOX_DDL = """
CREATE TABLE IF NOT EXISTS inbox_threads (
    conversation_urn TEXT PRIMARY KEY,
    participant_public_id TEXT NOT NULL,
    folder TEXT NOT NULL DEFAULT 'other',
    last_message_at TEXT,
    last_inbound_at TEXT,
    last_outbound_at TEXT,
    last_scanned_at TEXT,
    latest_inbound_text TEXT
);

CREATE TABLE IF NOT EXISTS inbox_messages (
    linkedin_message_urn TEXT PRIMARY KEY,
    conversation_urn TEXT NOT NULL,
    is_outgoing INTEGER NOT NULL DEFAULT 0,
    body TEXT,
    sent_at TEXT,
    FOREIGN KEY (conversation_urn) REFERENCES inbox_threads(conversation_urn)
);

CREATE TABLE IF NOT EXISTS inbox_opportunities (
    conversation_urn TEXT PRIMARY KEY,
    is_job_related INTEGER NOT NULL DEFAULT 0,
    confidence REAL,
    extracted_title TEXT,
    extracted_company TEXT,
    reasoning TEXT,
    classified_at TEXT,
    FOREIGN KEY (conversation_urn) REFERENCES inbox_threads(conversation_urn)
);

CREATE TABLE IF NOT EXISTS inbox_replies (
    conversation_urn TEXT PRIMARY KEY,
    reply_status TEXT NOT NULL DEFAULT 'pending',
    reply_message TEXT,
    reply_mode TEXT,
    drafted_at TEXT,
    sent_at TEXT,
    skip_reason TEXT,
    error TEXT,
    FOREIGN KEY (conversation_urn) REFERENCES inbox_threads(conversation_urn)
);

CREATE TABLE IF NOT EXISTS inbox_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_urn TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inbox_threads_public_id
    ON inbox_threads(participant_public_id);
CREATE INDEX IF NOT EXISTS idx_inbox_replies_status
    ON inbox_replies(reply_status);
CREATE INDEX IF NOT EXISTS idx_inbox_audit_urn
    ON inbox_audit_events(conversation_urn);
CREATE INDEX IF NOT EXISTS idx_inbox_audit_created
    ON inbox_audit_events(created_at);
"""

_INBOX_OPPORTUNITY_COLUMNS: dict[str, str] = {
    "intent": "TEXT",
    "intent_confidence": "REAL",
    "apply_url": "TEXT",
    "ats_vendor": "TEXT",
}

_INBOX_REPLY_COLUMNS: dict[str, str] = {
    "approved_at": "TEXT",
    "approved_by": "TEXT",
}


def ensure_inbox_columns(conn: sqlite3.Connection | None = None) -> list[str]:
    """Add v2 columns to inbox tables (idempotent forward migration)."""
    if conn is None:
        from applypilot.database import get_connection

        conn = get_connection()

    added: list[str] = []
    opp_cols = {row[1] for row in conn.execute("PRAGMA table_info(inbox_opportunities)").fetchall()}
    for col, dtype in _INBOX_OPPORTUNITY_COLUMNS.items():
        if col not in opp_cols:
            conn.execute(f"ALTER TABLE inbox_opportunities ADD COLUMN {col} {dtype}")
            added.append(f"inbox_opportunities.{col}")

    reply_cols = {row[1] for row in conn.execute("PRAGMA table_info(inbox_replies)").fetchall()}
    for col, dtype in _INBOX_REPLY_COLUMNS.items():
        if col not in reply_cols:
            conn.execute(f"ALTER TABLE inbox_replies ADD COLUMN {col} {dtype}")
            added.append(f"inbox_replies.{col}")

    if added:
        conn.commit()
    return added


def init_inbox_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(INBOX_DDL)
    conn.commit()
    ensure_inbox_columns(conn)


def get_inbox_stats(conn: sqlite3.Connection) -> dict:
    return {
        "inbox_threads": conn.execute("SELECT COUNT(*) FROM inbox_threads").fetchone()[0],
        "inbox_job_related": conn.execute(
            "SELECT COUNT(*) FROM inbox_opportunities WHERE is_job_related = 1"
        ).fetchone()[0],
        "inbox_drafted": conn.execute(
            "SELECT COUNT(*) FROM inbox_replies WHERE reply_status = 'drafted'"
        ).fetchone()[0],
        "inbox_approved": conn.execute(
            "SELECT COUNT(*) FROM inbox_replies WHERE approved_at IS NOT NULL"
        ).fetchone()[0],
        "inbox_sent": conn.execute(
            "SELECT COUNT(*) FROM inbox_replies WHERE reply_status = 'sent'"
        ).fetchone()[0],
        "inbox_skipped": conn.execute(
            "SELECT COUNT(*) FROM inbox_replies WHERE reply_status = 'skipped'"
        ).fetchone()[0],
        "inbox_audit_events": conn.execute("SELECT COUNT(*) FROM inbox_audit_events").fetchone()[0],
    }
