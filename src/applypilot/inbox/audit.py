"""Append-only audit log for inbox classify, gate, approve, and send events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(
    conversation_urn: str | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO inbox_audit_events (conversation_urn, event_type, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            conversation_urn,
            event_type,
            json.dumps(payload or {}, default=str),
            _utc_now(),
        ),
    )
    conn.commit()


def list_audit_events(
    *,
    limit: int = 50,
    conversation_urn: str | None = None,
    participant_public_id: str | None = None,
) -> list[dict]:
    conn = get_connection()
    if participant_public_id:
        rows = conn.execute(
            """
            SELECT e.id, e.conversation_urn, e.event_type, e.payload_json, e.created_at,
                   t.participant_public_id
            FROM inbox_audit_events e
            LEFT JOIN inbox_threads t ON t.conversation_urn = e.conversation_urn
            WHERE t.participant_public_id = ?
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (participant_public_id, limit),
        ).fetchall()
    elif conversation_urn:
        rows = conn.execute(
            """
            SELECT e.id, e.conversation_urn, e.event_type, e.payload_json, e.created_at,
                   t.participant_public_id
            FROM inbox_audit_events e
            LEFT JOIN inbox_threads t ON t.conversation_urn = e.conversation_urn
            WHERE e.conversation_urn = ?
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (conversation_urn, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT e.id, e.conversation_urn, e.event_type, e.payload_json, e.created_at,
                   t.participant_public_id
            FROM inbox_audit_events e
            LEFT JOIN inbox_threads t ON t.conversation_urn = e.conversation_urn
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    out: list[dict] = []
    for row in rows:
        item = dict(row)
        raw = item.pop("payload_json", None)
        if raw:
            try:
                item["payload"] = json.loads(raw)
            except json.JSONDecodeError:
                item["payload"] = {"raw": raw}
        else:
            item["payload"] = {}
        out.append(item)
    return out
