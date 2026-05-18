"""Send the fixed inbox reply to approved, eligible job threads via OpenOutreach."""

from __future__ import annotations

import logging
from typing import Any

from applypilot.inbox.audit import log_event
from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.eligibility import eligible_skip_reason, is_valid_public_id
from applypilot.inbox.intents import INTENT_APPLY_REQUEST
from applypilot.inbox.ranker import build_ranked_queue
from applypilot.inbox.store import (
    list_send_candidates,
    mark_sent,
    mark_skipped,
    update_participant_public_id,
)
from applypilot.outreach.openoutreach_client import OpenOutreachClient, OpenOutreachError

logger = logging.getLogger(__name__)


def _unwrap_api_result(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("result")
    if isinstance(inner, dict):
        return inner
    return payload


def resolve_vanity_public_id(
    client: OpenOutreachClient,
    raw_id: str,
    *,
    campaign: str | None,
) -> str:
    if not raw_id:
        return raw_id
    if not raw_id.startswith("ACo"):
        return raw_id
    try:
        payload = client.scrape_profile(raw_id, campaign=campaign, wait=True)
        data = _unwrap_api_result(payload)
        vanity = data.get("public_id")
        if vanity and vanity != raw_id:
            return str(vanity)
    except OpenOutreachError as exc:
        logger.warning("Scrape failed for %s: %s", raw_id, exc)
    return raw_id


def send_inbox(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    require_unanswered: bool | None = None,
    approved_only: bool = True,
) -> dict:
    cfg = settings or load_inbox_config()
    unanswered = (
        cfg.require_unanswered_inbound
        if require_unanswered is None
        else require_unanswered
    )
    lim = limit if limit is not None else cfg.max_sends_per_run
    message = cfg.fixed_reply_message
    client = OpenOutreachClient(cfg.openoutreach_base_url, cfg.openoutreach_api_key)

    sent = 0
    skipped = 0
    errors = 0
    results: list[dict] = []

    ranked = build_ranked_queue(
        settings=cfg, limit=lim * 5, require_unanswered=unanswered
    )
    eligible_urns = {
        row["conversation_urn"]
        for row in ranked
        if row.get("eligible_to_send") and row.get("conversation_urn")
    }
    seen_public_ids: set[str] = set()
    candidates = list_send_candidates(
        lim * 5,
        approved_only=approved_only and not dry_run,
        folder=cfg.inbox_folder,
    )
    if approved_only and not dry_run and not candidates:
        return {
            "dry_run": dry_run,
            "approved_only": approved_only,
            "skipped": 0,
            "errors": 0,
            "results": [],
            "sent": 0,
            "message": "No approved drafted threads. Run: applypilot inbox approve <public_id>",
        }

    for thread in candidates:
        if sent >= lim:
            break

        urn = (thread.get("conversation_urn") or "").strip()
        if not urn:
            skipped += 1
            results.append(
                {
                    "public_id": thread.get("participant_public_id"),
                    "status": "skipped",
                    "reason": "missing_conversation_urn",
                }
            )
            continue
        if urn not in eligible_urns:
            mark_skipped(urn, "not_in_secondary_filter")
            log_event(urn, "gated", {"skip_reason": "not_in_secondary_filter", "stage": "send"})
            skipped += 1
            results.append(
                {
                    "public_id": thread.get("participant_public_id"),
                    "status": "skipped",
                    "reason": "not_in_secondary_filter",
                }
            )
            continue

        opp = {
            "is_job_related": bool(thread.get("is_job_related")),
            "confidence": thread.get("confidence"),
            "intent": thread.get("intent") or INTENT_APPLY_REQUEST,
        }
        skip = eligible_skip_reason(thread, opp, require_unanswered=unanswered)
        if skip:
            mark_skipped(urn, skip)
            log_event(urn, "gated", {"skip_reason": skip, "stage": "send"})
            skipped += 1
            results.append(
                {"public_id": thread.get("participant_public_id"), "status": "skipped", "reason": skip}
            )
            continue

        if approved_only and not dry_run and not thread.get("approved_at"):
            log_event(urn, "gated", {"skip_reason": "not_approved", "stage": "send"})
            skipped += 1
            results.append(
                {
                    "public_id": thread.get("participant_public_id"),
                    "status": "skipped",
                    "reason": "not_approved",
                }
            )
            continue

        raw_id = thread.get("participant_public_id") or ""
        public_id = resolve_vanity_public_id(client, raw_id, campaign=cfg.openoutreach_campaign)
        if public_id != raw_id:
            update_participant_public_id(urn, public_id)

        if not is_valid_public_id(public_id):
            mark_skipped(urn, "invalid_public_id")
            log_event(urn, "gated", {"skip_reason": "invalid_public_id", "stage": "send"})
            skipped += 1
            results.append(
                {"public_id": public_id, "status": "skipped", "reason": "invalid_public_id"}
            )
            continue

        pid_key = public_id.lower()
        if pid_key in seen_public_ids:
            mark_skipped(urn, "duplicate_public_id")
            log_event(urn, "gated", {"skip_reason": "duplicate_public_id", "stage": "send"})
            skipped += 1
            results.append(
                {"public_id": public_id, "status": "skipped", "reason": "duplicate_public_id"}
            )
            continue
        seen_public_ids.add(pid_key)

        body = (thread.get("reply_message") or message).strip()

        entry = {
            "public_id": public_id,
            "conversation_urn": urn,
            "message": body,
        }

        log_event(
            urn,
            "send_attempt",
            {"public_id": public_id, "dry_run": dry_run, "approved": bool(thread.get("approved_at"))},
        )

        if dry_run:
            entry["status"] = "would_send"
            results.append(entry)
            sent += 1
            continue

        try:
            api_result = client.message(
                public_id,
                body,
                campaign=cfg.openoutreach_campaign,
                conversation_urn=urn,
                via="conversation",
                wait=True,
                timeout=180.0,
            )
            mark_sent(urn)
            entry["status"] = "sent"
            entry["api"] = _unwrap_api_result(api_result)
            log_event(urn, "send_ok", {"public_id": public_id})
            results.append(entry)
            sent += 1
        except OpenOutreachError as exc:
            mark_skipped(urn, "send_failed", str(exc))
            entry["status"] = "failed"
            entry["error"] = str(exc)
            log_event(urn, "send_fail", {"public_id": public_id, "error": str(exc)})
            results.append(entry)
            errors += 1
            logger.error("Send failed for %s: %s", public_id, exc)

    out: dict = {
        "dry_run": dry_run,
        "approved_only": approved_only,
        "fixed_message": message,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }
    if dry_run:
        out["would_send"] = sent
    else:
        out["sent"] = sent
    return out
