"""Dry-run pipeline with mocked scan and LLM."""

from applypilot.database import init_db
from applypilot.inbox.config import InboxSettings
from applypilot.inbox.runner import run_inbox_pipeline
from applypilot.inbox.store import upsert_thread_from_sync


def test_run_inbox_pipeline_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    init_db()

    upsert_thread_from_sync(
        {
            "conversation_urn": "urn:li:fsd_conversation:abc",
            "public_id": "recruiter-1",
            "folder": "other",
            "last_message_at": "2026-05-10T12:00:00+00:00",
            "last_inbound_at": "2026-05-10T12:00:00+00:00",
            "last_outbound_at": None,
            "latest_inbound_text": "We are hiring a Senior Engineer at FooCorp.",
            "messages": [],
        }
    )

    monkeypatch.setattr(
        "applypilot.inbox.runner.scan_inbox",
        lambda **kwargs: {"threads_synced": 0},
    )
    monkeypatch.setattr(
        "applypilot.inbox.runner.classify_inbox",
        lambda **kwargs: {"classified": 1, "job_related": 1, "errors": 0},
    )
    monkeypatch.setattr(
        "applypilot.inbox.runner.apply_fixed_replies",
        lambda **kwargs: {"staged": 1, "skipped": 0, "message": "Hi test."},
    )
    monkeypatch.setattr(
        "applypilot.inbox.runner.send_inbox",
        lambda **kwargs: {
            "dry_run": True,
            "would_send": 1,
            "skipped": 0,
            "errors": 0,
            "results": [],
            "fixed_message": "Hi test.",
        },
    )

    cfg = InboxSettings(
        enabled=True,
        inbox_folder="other",
        since_days=14,
        scan_limit=10,
        classify_limit=10,
        max_sends_per_run=5,
        job_confidence_threshold=0.7,
        fixed_reply_message="Hi test.",
        openoutreach_base_url="http://127.0.0.1:8741/v1",
        openoutreach_api_key="test",
        openoutreach_campaign="test",
        require_gemini=False,
        require_unanswered_inbound=True,
        sync_scroll_passes=8,
        sync_max_pages=20,
        require_approval_for_send=True,
    )
    report = run_inbox_pipeline(settings=cfg, dry_run=True)
    assert report["dry_run"] is True
    assert "send" in report
    assert report["send"]["would_send"] == 1
