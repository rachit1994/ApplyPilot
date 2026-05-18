#!/usr/bin/env python3
"""One-shot live test: scan → classify → draft → send 1 inbox reply; print outcome."""

from __future__ import annotations

import json
import sys

from applypilot.config import load_env, ensure_dirs
from applypilot.database import init_db
from applypilot.inbox.classifier import classify_inbox
from applypilot.inbox.config import load_inbox_config
from applypilot.inbox.drafter import draft_inbox
from applypilot.inbox.scanner import scan_inbox
from applypilot.inbox.store import list_send_candidates
from applypilot.outreach.openoutreach_client import OpenOutreachClient, OpenOutreachError
from applypilot.inbox.store import mark_sent, mark_skipped
from applypilot.inbox.gates import should_skip_reply


def main() -> int:
    load_env()
    ensure_dirs()
    init_db()
    cfg = load_inbox_config()

    print("=== Step 1: scan (Other tab) ===")
    try:
        scan = scan_inbox(settings=cfg, limit=min(cfg.scan_limit, 15))
        print(json.dumps(scan, indent=2))
    except Exception as exc:
        print(f"SCAN FAILED: {exc}")
        return 1

    print("\n=== Step 2: classify ===")
    try:
        clf = classify_inbox(settings=cfg, limit=cfg.classify_limit)
        print(json.dumps(clf, indent=2))
    except Exception as exc:
        print(f"CLASSIFY FAILED: {exc}")
        return 1

    print("\n=== Step 3: draft ===")
    try:
        drf = draft_inbox(settings=cfg, limit=cfg.classify_limit)
        print(json.dumps(drf, indent=2))
    except Exception as exc:
        print(f"DRAFT FAILED: {exc}")
        return 1

    candidates = list_send_candidates(5)
    if not candidates:
        print("\nNo drafted send candidates. Check classify/draft counts or send gates.")
        return 2

    thread = candidates[0]
    opp = {
        "is_job_related": bool(thread.get("is_job_related")),
        "confidence": thread.get("confidence"),
    }
    skip = should_skip_reply(thread, opp)
    if skip:
        print(f"\nTop candidate skipped: {skip}")
        return 2

    public_id = thread["participant_public_id"]
    message = (thread.get("reply_message") or "").strip()
    urn = thread["conversation_urn"]

    print("\n=== Step 4: send (live) ===")
    print(f"public_id: {public_id}")
    print(f"conversation_urn: {urn}")
    print(f"reply_mode: {thread.get('reply_mode')}")
    print(f"message ({len(message)} chars):\n---\n{message}\n---")

    client = OpenOutreachClient(cfg.openoutreach_base_url, cfg.openoutreach_api_key)
    try:
        result = client.message(
            public_id,
            message,
            campaign=cfg.openoutreach_campaign,
            conversation_urn=urn,
            via="conversation",
            wait=True,
            timeout=180.0,
        )
        mark_sent(urn)
        print("\nSUCCESS: message sent")
        print(json.dumps(result, indent=2, default=str))
        return 0
    except OpenOutreachError as exc:
        mark_skipped(urn, "send_failed", str(exc))
        print(f"\nFAILED: {exc}")
        if exc.status_code:
            print(f"HTTP status: {exc.status_code}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
