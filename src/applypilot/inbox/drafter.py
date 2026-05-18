"""Apply the same fixed reply to every job-classified thread."""

from __future__ import annotations

import logging

from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.eligibility import eligible_skip_reason, list_eligible_other_threads
from applypilot.inbox.store import save_draft

logger = logging.getLogger(__name__)


def apply_fixed_replies(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
    require_unanswered: bool | None = None,
) -> dict:
    """Stage fixed message on Other-tab threads where they asked you to apply."""
    cfg = settings or load_inbox_config()
    lim = limit if limit is not None else cfg.classify_limit
    unanswered = (
        cfg.require_unanswered_inbound
        if require_unanswered is None
        else require_unanswered
    )
    message = cfg.fixed_reply_message
    if not message:
        raise ValueError("fixed_reply_message is empty in inbox.yaml")

    staged = 0
    skipped = 0

    for thread in list_eligible_other_threads(
        settings=cfg, limit=lim, require_unanswered=unanswered
    ):
        opp = {
            "is_job_related": True,
            "confidence": thread.get("confidence"),
            "intent": thread.get("intent"),
        }
        skip = eligible_skip_reason(thread, opp, require_unanswered=unanswered)
        if skip:
            skipped += 1
            continue
        save_draft(thread["conversation_urn"], message, "fixed")
        staged += 1

    return {"staged": staged, "skipped": skipped, "message": message}


def draft_inbox(*, settings: InboxSettings | None = None, limit: int | None = None) -> dict:
    """Alias for apply_fixed_replies (CLI: inbox draft)."""
    return apply_fixed_replies(settings=settings, limit=limit)
