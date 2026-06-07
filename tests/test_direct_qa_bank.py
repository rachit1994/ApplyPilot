"""Tests for the Resolver Tier-1 Q&A bank: normalization, collision safety,
store/lookup roundtrip, and the template-never-served guarantee."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.apply.direct import qa_bank as qb


@pytest.fixture
def qa_conn(tmp_path: Path, monkeypatch):
    from applypilot import config, database
    database.close_connection()
    conn = database.init_db()
    yield conn
    database.close_connection()


def test_normalize_text():
    assert qb.normalize_text("  Years   of Experience? ") == "years of experience"
    assert qb.normalize_text("E-mail Address!") == "e mail address"
    assert qb.normalize_text(None) == ""
    # Idempotent.
    once = qb.normalize_text("Why  Us??")
    assert qb.normalize_text(once) == once


def test_key_collision_safety_label_vs_label():
    # The canonical over-collapse trap: same stem, different real questions.
    k1 = qb.question_key("Total years of experience", answer_type="number")
    k2 = qb.question_key("Years of experience with Python", answer_type="number")
    assert k1 != k2


def test_key_collision_safety_section_header():
    # "Email" under Referrer must not collide with "Email" under Personal.
    k1 = qb.question_key("Email", section_header="Personal Information")
    k2 = qb.question_key("Email", section_header="Referrer Information")
    assert k1 != k2


def test_key_collision_safety_name_attr_and_type():
    assert qb.question_key("Name", name_attr="full_name") != qb.question_key(
        "Name", name_attr="company_name"
    )
    assert qb.question_key("Choice", answer_type="text") != qb.question_key(
        "Choice", answer_type="select"
    )


def test_store_lookup_roundtrip(qa_conn):
    qb.store("Desired salary", "180000", answer_type="number", conn=qa_conn)
    assert qb.lookup("Desired salary", answer_type="number", conn=qa_conn) == "180000"


def test_lookup_miss_returns_none(qa_conn):
    assert qb.lookup("Never seen", conn=qa_conn) is None


def test_template_never_served_from_cache(qa_conn):
    qb.store("Why here?", "PROMPT {company}", answer_type="template", conn=qa_conn)
    # Looked up as template -> None (forces Gemini re-render).
    assert qb.lookup("Why here?", answer_type="template", conn=qa_conn) is None


def test_store_is_idempotent_upsert(qa_conn):
    qb.store("Phone", "111", answer_type="text", conn=qa_conn)
    qb.store("Phone", "222", answer_type="text", conn=qa_conn)
    assert qb.lookup("Phone", answer_type="text", conn=qa_conn) == "222"
    assert qb.count(conn=qa_conn) == 1


def test_lookup_bumps_hit_count(qa_conn):
    qb.store("Email", "a@b.com", answer_type="text", conn=qa_conn)
    qb.lookup("Email", answer_type="text", conn=qa_conn)
    qb.lookup("Email", answer_type="text", conn=qa_conn)
    key = qb.question_key("Email", answer_type="text")
    hits = qa_conn.execute(
        "SELECT hit_count FROM qa_bank WHERE question_key = ?", (key,)
    ).fetchone()[0]
    assert hits == 2


def test_invalid_answer_type_rejected(qa_conn):
    with pytest.raises(ValueError):
        qb.store("X", "y", answer_type="bogus", conn=qa_conn)
