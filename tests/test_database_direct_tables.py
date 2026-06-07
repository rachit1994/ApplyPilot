"""Tests for the Direct-Apply DB additions: qa_bank, apply_outcomes."""

from __future__ import annotations

import pytest

from applypilot import database as db
from applypilot.db.dialect import table_exists


@pytest.fixture
def conn(isolated_db):
    db.close_connection()
    c = db.init_db()
    yield c
    db.close_connection()


def test_new_tables_created(conn):
    assert table_exists(conn, "qa_bank")
    assert table_exists(conn, "apply_outcomes")


def test_init_db_is_idempotent(isolated_db):
    db.close_connection()
    db.init_db()
    db.close_connection()
    db.init_db()
    row = db.get_connection().execute("SELECT COUNT(*) AS c FROM qa_bank").fetchone()
    assert int(row["c"]) == 0


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
