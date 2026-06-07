"""Tests for per-family escalation caps (W3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from applypilot.apply.direct import unblock_learning


class _FakePage:
    url = "https://acme.wd5.myworkdayjobs.com/job"

    def wait_for_timeout(self, _ms: int) -> None:
        return None


@pytest.fixture
def fake_snapshot(monkeypatch):
    snap = {
        "url": "https://example.com/apply",
        "title": "Apply",
        "clickables": ["Accept all", "Apply now"],
        "fields": [],
        "has_password_field": False,
        "body_excerpt": "",
        "_form": MagicMock(),
    }
    monkeypatch.setattr(unblock_learning.unblock, "_snapshot", lambda _page: snap)
    monkeypatch.setattr(
        unblock_learning.extractor,
        "extract_fields",
        lambda _page: snap["_form"],
    )
    monkeypatch.setattr(
        unblock_learning.unblock,
        "_has_identity_form",
        lambda _form: False,
    )
    return snap


def test_recent_fail_rate_all_failures():
    from applypilot.apply.direct import review_log as rl
    from applypilot.database import get_connection

    conn = get_connection()
    for _ in range(6):
        rl.log_event(
            conn,
            ats_family="workday",
            tier="gemini",
            action_type="click",
            outcome="no_change",
        )
    attempts, fail_fraction = rl.recent_fail_rate(conn, ats_family="workday")
    assert attempts == 6
    assert fail_fraction == 1.0


def test_run_unblock_capped_when_fail_rate_high(fake_snapshot, monkeypatch):
    from applypilot.apply.direct import review_log as rl
    from applypilot.database import get_connection

    conn = get_connection()
    for _ in range(6):
        rl.log_event(
            conn,
            ats_family="workday",
            tier="gemini",
            action_type="click",
            outcome="no_change",
        )

    monkeypatch.setattr(unblock_learning.unblock, "unblock_enabled", lambda: True)
    monkeypatch.setattr(unblock_learning.unblock, "_dismiss_cookies", lambda _p: False)
    monkeypatch.setattr(unblock_learning, "_playbook", None)

    with patch.object(unblock_learning, "_gemini_decide") as gemini:
        with pytest.raises(unblock_learning.EscalationCapHit):
            unblock_learning.run_unblock_with_learning(
                _FakePage(),
                {"url": "https://example.com/job"},
                family="workday",
                max_steps=3,
            )
        gemini.assert_not_called()


def test_run_unblock_runs_when_below_cap(fake_snapshot, monkeypatch):
    monkeypatch.setattr(unblock_learning.unblock, "unblock_enabled", lambda: True)
    monkeypatch.setattr(unblock_learning.unblock, "_dismiss_cookies", lambda _p: False)
    monkeypatch.setattr(unblock_learning, "_playbook", None)

    with patch.object(unblock_learning, "_gemini_decide", return_value=None) as gemini:
        unblock_learning.run_unblock_with_learning(
            _FakePage(),
            {"url": "https://example.com/job"},
            family="workday",
            max_steps=1,
        )
        gemini.assert_called_once()


def test_generic_cap_is_scoped_to_apex_host(fake_snapshot, monkeypatch):
    from applypilot.apply.direct import review_log as rl
    from applypilot.database import get_connection

    conn = get_connection()
    for _ in range(6):
        rl.log_event(
            conn,
            ats_family="generic",
            apex_host="failed.example.com",
            tier="gemini",
            action_type="click",
            outcome="no_change",
        )

    monkeypatch.setattr(unblock_learning.unblock, "unblock_enabled", lambda: True)
    monkeypatch.setattr(unblock_learning.unblock, "_dismiss_cookies", lambda _p: False)
    monkeypatch.setattr(unblock_learning, "_playbook", None)

    with patch.object(unblock_learning, "_gemini_decide", return_value=None) as gemini:
        unblock_learning.run_unblock_with_learning(
            _FakePage(),
            {"url": "https://fresh.example.com/job"},
            family="generic",
            apex_host="fresh.example.com",
            max_steps=1,
        )
        gemini.assert_called_once()
