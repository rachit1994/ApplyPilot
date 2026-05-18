"""Persistence helpers for inbox tables."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from applypilot.database import get_connection
from applypilot.inbox.ats import extract_ats_from_text
from applypilot.inbox.intents import INTENT_APPLY_REQUEST


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clear_inbox_data() -> None:
    """Remove cached threads (use before re-scanning Other tab after a Focused sync)."""
    conn = get_connection()
    conn.execute("DELETE FROM inbox_audit_events")
    conn.execute("DELETE FROM inbox_messages")
    conn.execute("DELETE FROM inbox_replies")
    conn.execute("DELETE FROM inbox_opportunities")
    conn.execute("DELETE FROM inbox_threads")
    conn.commit()


def _inbound_from_messages(messages: list[dict]) -> tuple[str, str | None, str | None]:
    inbound = [m for m in messages if not m.get("is_outgoing")]
    outbound = [m for m in messages if m.get("is_outgoing")]
    latest = (inbound[-1].get("text") or "").strip() if inbound else ""
    last_in = inbound[-1].get("delivered_at") or inbound[-1].get("sent_at") if inbound else None
    last_out = outbound[-1].get("delivered_at") or outbound[-1].get("sent_at") if outbound else None
    return latest, last_in, last_out


def upsert_thread_from_sync(item: dict) -> None:
    conn = get_connection()
    now = _utc_now()
    messages = item.get("messages") or []
    derived_latest, derived_in, derived_out = _inbound_from_messages(messages)
    latest_inbound = (item.get("latest_inbound_text") or derived_latest or "").strip()
    last_inbound = item.get("last_inbound_at") or derived_in
    last_outbound = item.get("last_outbound_at") or derived_out
    conn.execute(
        """
        INSERT INTO inbox_threads (
            conversation_urn, participant_public_id, folder,
            last_message_at, last_inbound_at, last_outbound_at,
            last_scanned_at, latest_inbound_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_urn) DO UPDATE SET
            participant_public_id = excluded.participant_public_id,
            folder = excluded.folder,
            last_message_at = excluded.last_message_at,
            last_inbound_at = excluded.last_inbound_at,
            last_outbound_at = excluded.last_outbound_at,
            last_scanned_at = excluded.last_scanned_at,
            latest_inbound_text = COALESCE(excluded.latest_inbound_text, inbox_threads.latest_inbound_text)
        """,
        (
            item["conversation_urn"],
            item["public_id"],
            item.get("folder", "other"),
            item.get("last_message_at"),
            last_inbound,
            last_outbound,
            now,
            latest_inbound or None,
        ),
    )
    bodies: list[str] = []
    for msg in messages:
        urn = msg.get("linkedin_message_urn") or msg.get("urn")
        body = msg.get("body") or msg.get("text") or ""
        if body:
            bodies.append(body)
        if not urn:
            continue
        conn.execute(
            """
            INSERT INTO inbox_messages (linkedin_message_urn, conversation_urn, is_outgoing, body, sent_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(linkedin_message_urn) DO UPDATE SET
                body = excluded.body,
                sent_at = excluded.sent_at
            """,
            (
                urn,
                item["conversation_urn"],
                1 if msg.get("is_outgoing") else 0,
                body,
                msg.get("sent_at") or msg.get("delivered_at"),
            ),
        )
    conn.execute(
        """
        INSERT INTO inbox_replies (conversation_urn, reply_status)
        VALUES (?, 'pending')
        ON CONFLICT(conversation_urn) DO NOTHING
        """,
        (item["conversation_urn"],),
    )
    conn.commit()


def _thread_select_sql() -> str:
    return """
        SELECT t.*, o.is_job_related, o.confidence, o.extracted_title, o.extracted_company,
               o.reasoning, o.intent, o.intent_confidence, o.apply_url, o.ats_vendor,
               r.reply_status, r.reply_message, r.reply_mode, r.skip_reason,
               r.approved_at, r.approved_by
        FROM inbox_threads t
        LEFT JOIN inbox_opportunities o ON o.conversation_urn = t.conversation_urn
        LEFT JOIN inbox_replies r ON r.conversation_urn = t.conversation_urn
    """


def list_threads_for_classify(limit: int, *, folder: str = "other") -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        f"""
        {_thread_select_sql()}
        WHERE t.folder = ?
          AND (
            (t.latest_inbound_text IS NOT NULL AND length(trim(t.latest_inbound_text)) > 0)
            OR EXISTS (
              SELECT 1 FROM inbox_messages m
              WHERE m.conversation_urn = t.conversation_urn
                AND m.is_outgoing = 0
                AND m.body IS NOT NULL
                AND length(trim(m.body)) > 0
            )
          )
        ORDER BY t.last_inbound_at DESC
        LIMIT ?
        """,
        (folder, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_thread_transcript(conversation_urn: str, *, max_messages: int = 40) -> str:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT is_outgoing, body, sent_at
        FROM inbox_messages
        WHERE conversation_urn = ? AND body IS NOT NULL AND length(trim(body)) > 0
        ORDER BY sent_at ASC
        LIMIT ?
        """,
        (conversation_urn, max_messages),
    ).fetchall()
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        body = str(row["body"]).strip()
        speaker = "You" if row["is_outgoing"] else "Them"
        lines.append(f"{speaker}: {body}")
    return "\n".join(lines)


def save_classification(
    conversation_urn: str,
    *,
    is_job_related: bool,
    confidence: float,
    extracted_title: str | None,
    extracted_company: str | None,
    reasoning: str,
    intent: str | None = None,
    intent_confidence: float | None = None,
    apply_url: str | None = None,
    ats_vendor: str | None = None,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO inbox_opportunities (
            conversation_urn, is_job_related, confidence,
            extracted_title, extracted_company, reasoning, classified_at,
            intent, intent_confidence, apply_url, ats_vendor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_urn) DO UPDATE SET
            is_job_related = excluded.is_job_related,
            confidence = excluded.confidence,
            extracted_title = excluded.extracted_title,
            extracted_company = excluded.extracted_company,
            reasoning = excluded.reasoning,
            classified_at = excluded.classified_at,
            intent = excluded.intent,
            intent_confidence = excluded.intent_confidence,
            apply_url = excluded.apply_url,
            ats_vendor = excluded.ats_vendor
        """,
        (
            conversation_urn,
            1 if is_job_related else 0,
            confidence,
            extracted_title,
            extracted_company,
            reasoning,
            _utc_now(),
            intent,
            intent_confidence if intent_confidence is not None else confidence,
            apply_url,
            ats_vendor,
        ),
    )
    if not is_job_related:
        skip = "wrong_intent" if intent and intent != INTENT_APPLY_REQUEST else "not_asked_to_apply"
        conn.execute(
            """
            UPDATE inbox_replies SET reply_status = 'skipped', skip_reason = ?
            WHERE conversation_urn = ?
            """,
            (skip, conversation_urn),
        )
    conn.commit()


def save_draft(
    conversation_urn: str,
    message: str,
    reply_mode: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE inbox_replies SET
            reply_status = 'drafted',
            reply_message = ?,
            reply_mode = ?,
            drafted_at = ?,
            skip_reason = NULL,
            error = NULL
        WHERE conversation_urn = ?
        """,
        (message, reply_mode, _utc_now(), conversation_urn),
    )
    conn.commit()


def mark_sent(conversation_urn: str) -> None:
    conn = get_connection()
    now = _utc_now()
    conn.execute(
        """
        UPDATE inbox_replies SET reply_status = 'sent', sent_at = ?, skip_reason = NULL, error = NULL
        WHERE conversation_urn = ?
        """,
        (now, conversation_urn),
    )
    conn.execute(
        "UPDATE inbox_threads SET last_outbound_at = ? WHERE conversation_urn = ?",
        (now, conversation_urn),
    )
    conn.commit()


def mark_skipped(conversation_urn: str, reason: str, error: str | None = None) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE inbox_replies SET reply_status = 'skipped', skip_reason = ?, error = ?
        WHERE conversation_urn = ?
        """,
        (reason, error, conversation_urn),
    )
    conn.commit()


def update_participant_public_id(conversation_urn: str, public_id: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE inbox_threads SET participant_public_id = ? WHERE conversation_urn = ?",
        (public_id, conversation_urn),
    )
    conn.commit()


def resolve_thread_keys(keys: list[str]) -> list[str]:
    conn = get_connection()
    urns: list[str] = []
    for key in keys:
        if key.startswith("urn:"):
            urns.append(key)
            continue
        rows = conn.execute(
            """
            SELECT conversation_urn FROM inbox_threads
            WHERE participant_public_id = ? AND folder = 'other'
            """,
            (key,),
        ).fetchall()
        for row in rows:
            urns.append(row["conversation_urn"])
    return list(dict.fromkeys(urns))


def approve_threads(
    keys: list[str],
    *,
    approved_by: str = "local",
    draft_on_approve: bool = False,
    draft_message: str | None = None,
) -> dict:
    from applypilot.inbox.config import load_inbox_config
    from applypilot.inbox.drafter import apply_fixed_replies

    urns = resolve_thread_keys(keys)
    if not urns:
        return {"approved": 0, "urns": []}

    cfg = load_inbox_config()
    if draft_on_approve:
        apply_fixed_replies(settings=cfg, limit=max(len(urns) + 10, cfg.classify_limit))

    conn = get_connection()
    now = _utc_now()
    for urn in urns:
        conn.execute(
            """
            UPDATE inbox_replies SET approved_at = ?, approved_by = ?
            WHERE conversation_urn = ?
            """,
            (now, approved_by, urn),
        )
    conn.commit()

    from applypilot.inbox.audit import log_event

    for urn in urns:
        log_event(urn, "approved", {"approved_by": approved_by, "draft_on_approve": draft_on_approve})
    return {"approved": len(urns), "urns": urns}


def unapprove_threads(
    keys: list[str],
) -> dict:
    urns = resolve_thread_keys(keys)
    if not urns:
        return {"unapproved": 0}

    conn = get_connection()
    for urn in urns:
        conn.execute(
            """
            UPDATE inbox_replies SET approved_at = NULL, approved_by = NULL
            WHERE conversation_urn = ?
            """,
            (urn,),
        )
    conn.commit()

    from applypilot.inbox.audit import log_event

    for urn in urns:
        log_event(urn, "unapproved", {})
    return {"unapproved": len(urns), "urns": urns}


def list_send_candidates(
    limit: int,
    *,
    approved_only: bool = False,
    folder: str = "other",
) -> list[dict]:
    conn = get_connection()
    approved_clause = "AND r.approved_at IS NOT NULL" if approved_only else ""
    rows = conn.execute(
        f"""
        {_thread_select_sql()}
        WHERE t.folder = ?
          AND (
            o.intent = 'apply_request'
            OR (o.intent IS NULL AND o.is_job_related = 1)
          )
          AND r.reply_status = 'drafted'
          AND r.reply_message IS NOT NULL
          {approved_clause}
        ORDER BY t.last_inbound_at DESC
        LIMIT ?
        """,
        (folder, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def clear_non_eligible_drafts(eligible_urns: set[str]) -> dict:
    """Remove drafts/approvals on Other-tab threads outside the eligible set."""
    conn = get_connection()
    now = _utc_now()
    if not eligible_urns:
        cur = conn.execute(
            """
            UPDATE inbox_replies SET
                reply_status = 'skipped',
                skip_reason = 'not_in_secondary_filter',
                reply_message = NULL,
                approved_at = NULL,
                approved_by = NULL,
                drafted_at = NULL
            WHERE conversation_urn IN (
                SELECT conversation_urn FROM inbox_threads WHERE folder = 'other'
            )
            AND reply_status IN ('drafted', 'pending')
            """
        )
    else:
        placeholders = ",".join("?" * len(eligible_urns))
        cur = conn.execute(
            f"""
            UPDATE inbox_replies SET
                reply_status = 'skipped',
                skip_reason = 'not_in_secondary_filter',
                reply_message = NULL,
                approved_at = NULL,
                approved_by = NULL,
                drafted_at = NULL
            WHERE conversation_urn IN (
                SELECT conversation_urn FROM inbox_threads WHERE folder = 'other'
            )
            AND conversation_urn NOT IN ({placeholders})
            AND reply_status IN ('drafted', 'pending')
            """,
            tuple(eligible_urns),
        )
    conn.commit()
    return {"cleared": cur.rowcount, "at": now}
