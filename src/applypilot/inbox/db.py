"""LinkedIn inbox schema (Postgres; tables created by ``applypilot.db.schema``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from applypilot.db.dialect import scalar, table_columns
from applypilot.db.schema import INBOX_OPPORTUNITY_COLUMNS, INBOX_REPLY_COLUMNS, ensure_inbox_columns

if TYPE_CHECKING:
    from applypilot.db.connection import Connection


def init_inbox_schema(conn: Connection) -> None:
    """Ensure inbox forward migrations are applied."""
    ensure_inbox_columns(conn)
    conn.commit()


def clear_gmail_inbox_data() -> None:
    """Remove cached Gmail recruiter messages (re-scan)."""
    from applypilot.database import get_connection

    conn = get_connection()
    conn.execute("DELETE FROM inbox_gmail_messages")
    conn.commit()


def get_inbox_stats(conn: Connection) -> dict:
    return {
        "inbox_threads": int(scalar(conn.execute("SELECT COUNT(*) AS c FROM inbox_threads").fetchone()) or 0),
        "inbox_job_related": int(
            scalar(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inbox_opportunities WHERE is_job_related = 1"
                ).fetchone()
            )
            or 0
        ),
        "inbox_drafted": int(
            scalar(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inbox_replies WHERE reply_status = 'drafted'"
                ).fetchone()
            )
            or 0
        ),
        "inbox_approved": int(
            scalar(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inbox_replies WHERE approved_at IS NOT NULL"
                ).fetchone()
            )
            or 0
        ),
        "inbox_sent": int(
            scalar(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inbox_replies WHERE reply_status = 'sent'"
                ).fetchone()
            )
            or 0
        ),
        "inbox_skipped": int(
            scalar(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inbox_replies WHERE reply_status = 'skipped'"
                ).fetchone()
            )
            or 0
        ),
        "inbox_audit_events": int(
            scalar(conn.execute("SELECT COUNT(*) AS c FROM inbox_audit_events").fetchone()) or 0
        ),
    }
