"""Tests for the Direct-Apply DB additions: qa_bank, apply_outcomes, WAL."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot import database as db


@pytest.fixture
def conn(tmp_path: Path, monkeypatch):
    from applypilot import config

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.close_connection(db_path)
    c = db.init_db(db_path)
    yield c
    db.close_connection(db_path)


def test_new_tables_created(conn):
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "qa_bank" in tables
    assert "apply_outcomes" in tables


def test_wal_mode_enabled(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    from applypilot import config

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.close_connection(db_path)
    db.init_db(db_path)
    db.close_connection(db_path)
    # Second init must not raise (CREATE TABLE IF NOT EXISTS).
    c = db.init_db(db_path)
    assert c.execute("SELECT COUNT(*) FROM qa_bank").fetchone()[0] == 0


def test_record_apply_outcome(conn):
    db.record_apply_outcome(
        conn=conn,
        url="https://jobs.lever.co/acme/x",
        ats_family="lever",
        fingerprint="lever:url",
        result="applied",
        tier_resolved=1,
        fields_total=8,
        fields_llm=1,
        elapsed_ms=42000,
    )
    row = conn.execute(
        "SELECT url, ats_family, result, tier_resolved, escalated, "
        "fields_total, fields_llm FROM apply_outcomes"
    ).fetchone()
    assert row["url"] == "https://jobs.lever.co/acme/x"
    assert row["ats_family"] == "lever"
    assert row["result"] == "applied"
    assert row["tier_resolved"] == 1
    assert row["escalated"] == 0
    assert row["fields_total"] == 8
    assert row["fields_llm"] == 1


def test_record_apply_outcome_escalation(conn):
    db.record_apply_outcome(
        conn=conn,
        url="https://acme.myworkdayjobs.com/x",
        ats_family="workday",
        result="failed:workday_unknown_step",
        escalated=True,
        escalate_reason="workday_unknown_step",
    )
    row = conn.execute(
        "SELECT escalated, escalate_reason FROM apply_outcomes"
    ).fetchone()
    assert row["escalated"] == 1
    assert row["escalate_reason"] == "workday_unknown_step"
