"""Tests for workflow induction (W8)."""

from __future__ import annotations

import pytest

from applypilot.apply.direct import induction, playbook
from applypilot.apply.direct import review_log as rl
from applypilot.database import get_connection


@pytest.fixture
def conn():
    connection = get_connection()
    playbook.ensure_playbook_tables(connection)
    return connection


def test_induce_candidates_requires_min_support(conn):
    sig = "abc123"
    for _ in range(2):
        rl.log_event(
            conn,
            ats_family="greenhouse",
            state_sig=sig,
            tier="gemini",
            action_type="click",
            outcome="advanced",
            postcondition_met=True,
        )
    assert induction.induce_candidates(conn, min_support=3) == []

    rl.log_event(
        conn,
        ats_family="greenhouse",
        state_sig=sig,
        tier="gemini",
        action_type="click",
        outcome="advanced",
        postcondition_met=True,
    )
    rows = induction.induce_candidates(conn, min_support=3)
    assert len(rows) == 1
    assert rows[0]["state_sig"] == sig
    assert rows[0]["action_type"] == "click"
    assert rows[0]["support"] == 3


def test_induce_skips_already_trusted(conn):
    sig = playbook.state_signature(
        {"clickables": ["Apply"], "has_application_form": False},
        ats_family="greenhouse",
        apex_host="boards.greenhouse.io",
    )
    playbook.record_nav(
        sig,
        ats_family="greenhouse",
        apex_host="boards.greenhouse.io",
        action_type="click",
        action_args={"text": "Apply"},
        status="trusted",
        conn=conn,
    )
    for _ in range(3):
        rl.log_event(
            conn,
            ats_family="greenhouse",
            state_sig=sig,
            tier="gemini",
            action_type="click",
            outcome="advanced",
            postcondition_met=True,
        )
    assert induction.induce_candidates(conn, min_support=3) == []
