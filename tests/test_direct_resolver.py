"""Tests for the tiered Resolver (Tier 0 rules -> Tier 1 cache -> Tier 2 Gemini)."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.apply.direct import resolver as rz
from applypilot.apply.direct.profile_binding import Field

TOKENS = {
    "full_name": "Rachit Srivastava",
    "email": "rachit@example.com",
    "phone_digits": "5551234567",
    "require_sponsorship": "No",
    "years_experience": "8",
    "current_job_title": "Senior Software Engineer",
    "earliest_start_date": "Immediately",
    "city": "Toronto",
}


@pytest.fixture
def conn(tmp_path: Path, monkeypatch):
    from applypilot import config, database

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.close_connection(db_path)
    c = database.init_db(db_path)
    yield c
    database.close_connection(db_path)


def test_tier0_covers_standard_fields(conn):
    fields = [
        Field(label="First name", key="k1"),
        Field(label="Email", type="email", key="k2"),
        Field(label="Are you authorized to work?", key="k3"),
        Field(label="Gender", tag="select", options=("Male", "Female", "Decline to self-identify"), key="k4"),
    ]
    out = rz.resolve(fields, TOKENS, conn=conn, gemini_enabled=False)
    assert out.answers["k1"] == "Rachit"
    assert out.answers["k2"] == "rachit@example.com"
    assert out.answers["k3"] == "Yes"
    assert out.answers["k4"] == "Decline to self-identify"
    assert out.tier_max == 0
    assert out.unresolved == []


def test_tier1_cache_hit(conn):
    from applypilot.apply.direct import qa_bank

    qa_bank.store("Favorite framework", "Django", answer_type="text", conn=conn)
    fields = [Field(label="Favorite framework", key="k1")]
    out = rz.resolve(fields, TOKENS, conn=conn, gemini_enabled=False)
    assert out.answers["k1"] == "Django"
    assert out.tier_max == 1
    assert out.via["k1"] == "t1:cache"


def test_unresolved_required_tracked_when_gemini_off(conn):
    fields = [
        Field(label="What is your management philosophy?", tag="textarea", required=True, key="kq"),
    ]
    out = rz.resolve(fields, TOKENS, conn=conn, gemini_enabled=False)
    assert "kq" in out.unresolved
    assert "kq" in out.unresolved_required


def test_tier2_gemini_batch_and_writeback(conn, monkeypatch):
    # Mock the Gemini client to answer the one novel field.
    class FakeClient:
        model = "gemini-flash"

        def ask(self, prompt):
            assert "kq" in prompt  # the field key is in the payload
            return '{"kq": "I value autonomy and clear ownership."}'

    monkeypatch.setattr(rz, "get_client", lambda: FakeClient(), raising=False)
    monkeypatch.setattr(
        "applypilot.llm.get_client", lambda: FakeClient(), raising=False
    )

    fields = [Field(label="Management philosophy?", tag="textarea", required=True, key="kq")]
    out = rz.resolve(fields, TOKENS, conn=conn, gemini_enabled=True)
    assert out.answers["kq"].startswith("I value autonomy")
    assert out.tier_max == 2
    assert out.llm_field_count == 1
    # Writeback: a second resolve now hits Tier 1 (cache), no Gemini needed.
    out2 = rz.resolve(fields, TOKENS, conn=conn, gemini_enabled=False)
    assert out2.answers["kq"].startswith("I value autonomy")
    assert out2.tier_max == 1


def test_parse_json_answers_tolerates_fences():
    raw = "```json\n{\"a\": \"1\", \"b\": null}\n```"
    assert rz._parse_json_answers(raw) == {"a": "1"}
    assert rz._parse_json_answers("garbage") == {}


def test_select_answer_snapped_to_option(conn):
    # Tier-0 yields "Yes"; the select offers a worded variant -> snap to it.
    fields = [
        Field(
            label="Are you legally authorized to work?",
            tag="select",
            options=("Yes, I am authorized", "No"),
            key="k1",
        )
    ]
    out = rz.resolve(fields, TOKENS, conn=conn, gemini_enabled=False)
    assert out.answers["k1"] == "Yes, I am authorized"
