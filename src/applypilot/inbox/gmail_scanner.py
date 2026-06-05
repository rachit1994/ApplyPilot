"""Read-only Gmail scan for recruiter replies (same intent taxonomy as LinkedIn)."""

from __future__ import annotations

import logging
from datetime import timezone
from email.utils import parsedate_to_datetime

from applypilot.apply import gmail_auth
from applypilot.inbox.classifier import classify_message
from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.intents import (
    INTENT_AUTO_ACK,
    is_human_reply_intent,
    looks_like_auto_acknowledgement,
)
from applypilot.inbox.store import list_gmail_unclassified, upsert_gmail_message

logger = logging.getLogger(__name__)


def _header_date_to_iso(raw: str | None) -> str | None:
    """Normalize an RFC 2822 Gmail ``Date`` header to an ISO 8601 UTC string.

    Reply-rate windowing (reply_report) and reply dedup (job_match) compare
    ``reply_at`` lexicographically against ISO timestamps. Storing the raw
    header (e.g. "Wed, 03 Jun 2026 14:23:01 +0530") would make every Gmail
    reply sort/compare wrong, so parse it here at ingestion.
    """
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

# Inbound recruiter / hiring mail only (read-only metadata search).
_DEFAULT_RECRUITER_QUERY = (
    "newer_than:{days}d -from:me "
    "(subject:(interview OR application OR role OR position OR hiring OR recruiter OR opportunity) "
    "OR from:linkedin.com OR from:greenhouse.io OR from:lever.co OR from:ashbyhq.com "
    "OR from:workday.com OR from:smartrecruiters.com)"
)


def recruiter_gmail_query(*, since_days: int) -> str:
    return _DEFAULT_RECRUITER_QUERY.format(days=max(1, since_days))


def scan_gmail_inbox(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
    since_days: int | None = None,
    query: str | None = None,
) -> dict:
    """Fetch and classify Gmail messages. Never sends or mutates mail."""
    cfg = settings or load_inbox_config()
    days = since_days if since_days is not None else cfg.since_days
    lim = limit if limit is not None else cfg.scan_limit
    q = query or recruiter_gmail_query(since_days=days)

    if not gmail_auth.credentials_exist():
        return {
            "error": "gmail_not_configured",
            "hint": "Run applypilot gmail login (read-only OAuth).",
            "messages_fetched": 0,
            "messages_stored": 0,
            "classified": 0,
            "human_replies": 0,
        }

    try:
        summaries = gmail_auth.search_messages(q, lim)
    except Exception as exc:
        logger.error("Gmail scan failed: %s", exc)
        return {
            "error": str(exc),
            "query": q,
            "messages_fetched": 0,
            "messages_stored": 0,
            "classified": 0,
            "human_replies": 0,
        }

    stored = 0
    for summary in summaries:
        upsert_gmail_message(
            message_id=summary.message_id,
            thread_id=None,
            from_address=summary.from_,
            subject=summary.subject,
            snippet=summary.snippet,
            received_at=_header_date_to_iso(summary.date),
        )
        stored += 1

    classify_result = classify_gmail_messages(settings=cfg, limit=lim)
    return {
        "query": q,
        "messages_fetched": len(summaries),
        "messages_stored": stored,
        **classify_result,
    }


def classify_gmail_messages(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
) -> dict:
    cfg = settings or load_inbox_config()
    lim = limit if limit is not None else cfg.classify_limit
    classified = 0
    human_replies = 0
    errors = 0

    for row in list_gmail_unclassified(lim):
        text = " ".join(
            [
                row.get("subject") or "",
                row.get("snippet") or "",
            ]
        ).strip()
        if not text:
            continue
        try:
            result = classify_message(
                text,
                threshold=cfg.job_confidence_threshold,
            )
            intent = result["intent"]
            # ATS senders matched by the scan query send automated "application
            # received" mail on every apply; override those to auto_ack so they
            # are not counted as recruiter replies.
            ack_blob = " ".join(
                [
                    row.get("from_address") or "",
                    row.get("subject") or "",
                    row.get("snippet") or "",
                ]
            )
            if looks_like_auto_acknowledgement(ack_blob):
                intent = INTENT_AUTO_ACK
            from applypilot.inbox.store import save_gmail_classification

            save_gmail_classification(
                row["message_id"],
                intent=intent,
                intent_confidence=result.get("intent_confidence") or result["confidence"],
                extracted_title=result.get("extracted_title"),
                extracted_company=result.get("extracted_company"),
                reasoning=result.get("reasoning") or "",
            )
            classified += 1
            if is_human_reply_intent(intent):
                human_replies += 1
        except Exception as exc:
            logger.warning("Gmail classify failed for %s: %s", row["message_id"], exc)
            errors += 1

    return {
        "classified": classified,
        "human_replies": human_replies,
        "errors": errors,
    }
