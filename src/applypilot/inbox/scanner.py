"""Fetch LinkedIn Other-tab threads via OpenOutreach sync-inbox."""

from __future__ import annotations

import logging

from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.store import upsert_thread_from_sync
from applypilot.outreach.openoutreach_client import OpenOutreachClient, OpenOutreachError

logger = logging.getLogger(__name__)


def scan_inbox(*, settings: InboxSettings | None = None, limit: int | None = None) -> dict:
    cfg = settings or load_inbox_config()
    lim = limit if limit is not None else cfg.scan_limit
    # Click-walk sync: ~8s per thread in OpenOutreach browser_walk.
    sync_timeout = max(300.0, float(lim) * 12.0 + 120.0)
    client = OpenOutreachClient(
        cfg.openoutreach_base_url,
        cfg.openoutreach_api_key,
        timeout=sync_timeout,
    )
    try:
        payload = client.sync_inbox(
            since_days=cfg.since_days,
            limit=lim,
            include_messages=True,
            use_browser=True,
            scroll_passes=cfg.sync_scroll_passes,
            max_pages=cfg.sync_max_pages,
            wait=True,
            timeout=sync_timeout,
        )
    except OpenOutreachError as exc:
        logger.error("sync-inbox failed: %s", exc)
        raise

    threads = payload.get("threads") or []
    synced = 0
    for item in threads:
        urn = item.get("conversation_urn")
        public_id = (item.get("public_id") or item.get("participant_public_id") or "").strip()
        if not urn:
            continue
        messages = item.get("messages") or []
        if not public_id and not messages and not (item.get("latest_inbound_text") or "").strip():
            continue
        if not public_id:
            public_id = urn.rsplit(",", 1)[-1].strip(")") if "," in urn else urn[-12:]
        item = {**item, "public_id": public_id, "conversation_urn": urn}
        upsert_thread_from_sync(item)
        synced += 1

    return {
        "folder": payload.get("folder", cfg.inbox_folder),
        "inbox_type": payload.get("inbox_type", "SECONDARY"),
        "messaging_url": payload.get(
            "messaging_url",
            "https://www.linkedin.com/messaging/?inboxType=SECONDARY",
        ),
        "threads_returned": len(threads),
        "threads_synced": synced,
        "source": payload.get("source"),
    }
