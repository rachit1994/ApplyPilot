"""Tests for apply/direct/review_log.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from applypilot.apply.direct import review_log as rl
from applypilot.db.dialect import table_columns, table_exists


@pytest.fixture
def conn(isolated_db):
    from applypilot import database as db

    db.close_connection()
    c = db.init_db()
    yield c
    db.close_connection()


def test_ensure_review_log_table_creates_schema(conn):
    rl.ensure_review_log_table(conn)
    assert table_exists(conn, "review_log")
    cols = table_columns(conn, "review_log")
    assert "state_sig" in cols
    assert "tier" in cols
    assert "cost_usd" in cols


def test_log_event_inserts_row(conn):
    row_id = rl.log_event(
        conn,
        job_url="https://jobs.example.com/1",
        ats_family="greenhouse",
        apex_host="boards.greenhouse.io",
        state_sig="sig-abc",
        tier="gemini",
        action_type="click",
        action_args={"text": "Apply"},
        outcome="advanced",
        postcondition_met=True,
        cost_usd=0.01,
    )
    assert row_id == 1
    row = conn.execute("SELECT * FROM review_log WHERE id = 1").fetchone()
    assert row["job_url"] == "https://jobs.example.com/1"
    assert row["action_args"] == '{"text": "Apply"}'
    assert row["postcondition_met"] == 1
    assert row["cost_usd"] == pytest.approx(0.01)


def test_dedupe_clusters_groups_by_state_sig(conn):
    rl.ensure_review_log_table(conn)
    for _ in range(3):
        rl.log_event(conn, state_sig="sig-a", tier="gemini", action_type="click")
    for _ in range(2):
        rl.log_event(conn, state_sig="sig-b", tier="replay", action_type="accept_cookies")
    rl.log_event(conn, state_sig="sig-c", tier="claude", action_type="wait")

    clusters = rl.dedupe_clusters(conn, limit=10)
    assert len(clusters) == 3
    assert clusters[0]["state_sig"] == "sig-a"
    assert clusters[0]["count"] == 3
    assert clusters[1]["state_sig"] == "sig-b"
    assert clusters[1]["count"] == 2


def test_dedupe_clusters_ignores_empty_sig(conn):
    rl.log_event(conn, state_sig="", tier="gemini")
    rl.log_event(conn, state_sig=None, tier="gemini")
    rl.log_event(conn, state_sig="sig-real", tier="replay")
    clusters = rl.dedupe_clusters(conn)
    assert len(clusters) == 1
    assert clusters[0]["state_sig"] == "sig-real"


def test_cache_hit_rate_math(conn):
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(hours=48)).isoformat()
    recent_ts = (now - timedelta(hours=1)).isoformat()

    rl.log_event(conn, state_sig="s1", tier="replay", ts=recent_ts)
    rl.log_event(conn, state_sig="s2", tier="replay", ts=recent_ts)
    rl.log_event(conn, state_sig="s3", tier="gemini", ts=recent_ts)
    rl.log_event(conn, state_sig="s4", tier="claude", ts=recent_ts)
    rl.log_event(conn, state_sig="s5", tier="replay", ts=old_ts)
    rl.log_event(conn, state_sig="s6", tier="deterministic", ts=recent_ts)

    stats = rl.cache_hit_rate(conn, since_hours=24)
    assert stats["replay_count"] == 2
    assert stats["llm_count"] == 2
    assert stats["replay_pct"] == 50.0


def test_cache_hit_rate_empty_window(conn):
    stats = rl.cache_hit_rate(conn, since_hours=24)
    assert stats["replay_count"] == 0
    assert stats["llm_count"] == 0
    assert stats["replay_pct"] == 0.0


def test_recent_fail_rate_all_failures(conn):
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(hours=1)).isoformat()
    for _ in range(6):
        rl.log_event(
            conn,
            ats_family="workday",
            outcome="no_change",
            ts=recent_ts,
        )

    attempts, fail_fraction = rl.recent_fail_rate(conn, ats_family="workday")
    assert attempts == 6
    assert fail_fraction == pytest.approx(1.0)


def test_recent_fail_rate_mixed_outcomes(conn):
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(hours=1)).isoformat()
    rl.log_event(conn, ats_family="greenhouse", outcome="advanced", ts=recent_ts)
    rl.log_event(conn, ats_family="greenhouse", outcome="no_change", ts=recent_ts)
    rl.log_event(conn, ats_family="greenhouse", outcome="advanced", ts=recent_ts)

    attempts, fail_fraction = rl.recent_fail_rate(conn, ats_family="greenhouse")
    assert attempts == 3
    assert fail_fraction == pytest.approx(1 / 3)


def test_recent_fail_rate_replay_clicked_counts_as_success(conn):
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(hours=1)).isoformat()
    for _ in range(6):
        rl.log_event(
            conn,
            ats_family="workable",
            tier="replay",
            outcome="clicked",
            postcondition_met=True,
            ts=recent_ts,
        )

    attempts, fail_fraction = rl.recent_fail_rate(conn, ats_family="workable")
    assert attempts == 6
    assert fail_fraction == pytest.approx(0.0)


def test_recent_fail_rate_excludes_cap_tier_rows(conn):
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(hours=1)).isoformat()
    rl.log_event(
        conn,
        ats_family="workable",
        tier="cap",
        outcome="escalate_human",
        ts=recent_ts,
    )
    rl.log_event(
        conn,
        ats_family="workable",
        tier="replay",
        outcome="no_change",
        postcondition_met=False,
        ts=recent_ts,
    )

    attempts, fail_fraction = rl.recent_fail_rate(conn, ats_family="workable")
    assert attempts == 1
    assert fail_fraction == pytest.approx(1.0)


def test_recent_fail_rate_can_scope_to_apex_host(conn):
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(hours=1)).isoformat()
    for _ in range(6):
        rl.log_event(
            conn,
            ats_family="generic",
            apex_host="failed.example.com",
            outcome="no_change",
            ts=recent_ts,
        )
    rl.log_event(
        conn,
        ats_family="generic",
        apex_host="fresh.example.com",
        outcome="advanced",
        ts=recent_ts,
    )

    attempts, fail_fraction = rl.recent_fail_rate(
        conn, ats_family="generic", apex_host="fresh.example.com"
    )
    assert attempts == 1
    assert fail_fraction == pytest.approx(0.0)
