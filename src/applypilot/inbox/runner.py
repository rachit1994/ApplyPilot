"""Orchestrate inbox: LinkedIn Other tab → job classify → fixed reply → send."""

from __future__ import annotations

import logging

from applypilot.inbox.classifier import classify_inbox
from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.drafter import apply_fixed_replies
from applypilot.inbox.ranker import build_ranked_queue
from applypilot.inbox.scanner import scan_inbox
from applypilot.inbox.sender import send_inbox

logger = logging.getLogger(__name__)


def run_inbox_pipeline(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    require_unanswered: bool | None = None,
    do_scan: bool = True,
    do_classify: bool = True,
    do_draft: bool = True,
    do_send: bool = True,
    approved_only: bool | None = None,
) -> dict:
    cfg = settings or load_inbox_config()
    report: dict = {
        "folder": cfg.inbox_folder,
        "dry_run": dry_run,
        "fixed_message": cfg.fixed_reply_message,
    }

    if do_scan:
        report["scan"] = scan_inbox(settings=cfg, limit=limit)
    if do_classify:
        report["classify"] = classify_inbox(settings=cfg, limit=limit)
    if do_classify or do_draft or do_send:
        report["queue"] = build_ranked_queue(
            settings=cfg, limit=limit, require_unanswered=require_unanswered
        )
    if do_draft:
        report["prepare"] = apply_fixed_replies(
            settings=cfg, limit=limit, require_unanswered=require_unanswered
        )
    if do_send:
        require_approval = (
            cfg.require_approval_for_send
            if approved_only is None
            else bool(approved_only)
        )
        report["send"] = send_inbox(
            settings=cfg,
            limit=limit,
            dry_run=dry_run,
            require_unanswered=require_unanswered,
            approved_only=require_approval and not dry_run,
        )

    return report
