"""Tests for /api/learning self-learning endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        monkeypatch.setenv("APPLYPILOT_DIR", tmp)
        from applypilot import config
        from applypilot import database
        from applypilot.orchestration import events

        config.load_env()
        monkeypatch.setattr(config, "APP_DIR", Path(tmp))
        monkeypatch.setattr(config, "DB_PATH", db)
        monkeypatch.setattr(database, "DB_PATH", db)
        monkeypatch.setattr(events, "DB_PATH", db)
        database.close_connection()
        yield db
        database.close_connection(db)


def test_learning_stats_review_clusters_and_promote(temp_db):
    from applypilot.apply.direct import playbook
    from applypilot.apply.direct import review_log as rl
    from applypilot.apply.direct.playbook_seed import seed_nav_playbooks
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app

    init_db(temp_db)
    conn = get_connection(temp_db)
    seed_nav_playbooks(conn, families=["greenhouse"])
    row = conn.execute(
        "SELECT state_sig, scope FROM nav_playbook LIMIT 1"
    ).fetchone()
    assert row is not None
    state_sig = row["state_sig"]
    scope = row["scope"]

    rl.log_event(
        conn,
        ats_family="greenhouse",
        state_sig=state_sig,
        tier="replay",
        action_type="accept_cookies",
        outcome="advanced",
    )
    rl.log_event(
        conn,
        ats_family="greenhouse",
        state_sig=state_sig,
        tier="gemini",
        action_type="click",
        outcome="failed",
    )

    client = TestClient(create_app())

    stats = client.get("/api/learning/stats?since_hours=24")
    assert stats.status_code == 200
    body = stats.json()
    assert body["nav_playbook"]["total"] >= 1
    assert body["cache_hit"]["replay_count"] >= 1
    assert body["field_strategy_total"] == 0

    review = client.get("/api/learning/review?limit=10")
    assert review.status_code == 200
    events = review.json()["events"]
    assert len(events) >= 2

    clusters = client.get("/api/learning/clusters?limit=5")
    assert clusters.status_code == 200
    assert clusters.json()["clusters"][0]["state_sig"] == state_sig

    promote = client.post(
        "/api/learning/promote",
        json={"state_sig": state_sig, "scope": scope},
    )
    assert promote.status_code == 200
    assert promote.json()["status"] == "trusted"

    ban = client.post(
        "/api/learning/ban",
        json={"state_sig": state_sig, "scope": scope},
    )
    assert ban.status_code == 200
    assert ban.json()["status"] == "banned"

    entry = playbook.lookup_nav(state_sig, scope=scope, conn=conn)
    assert entry is not None
    assert entry.status == "banned"


def test_learning_promote_missing_returns_404(temp_db):
    from applypilot.database import init_db
    from applypilot.server.app import create_app

    init_db(temp_db)
    client = TestClient(create_app())
    res = client.post(
        "/api/learning/promote",
        json={"state_sig": "missing-sig", "scope": "host"},
    )
    assert res.status_code == 404
