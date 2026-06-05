"""Tests for unblock_learning integration wrapper (mocked, no browser)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from applypilot.apply.direct import unblock_learning


class _FakePage:
    url = "https://boards.greenhouse.io/acme/jobs/123"

    def wait_for_timeout(self, _ms: int) -> None:
        return None


def _trusted_entry(tool: str = "accept_cookies", args: dict | None = None):
    return SimpleNamespace(
        action_type=tool,
        action_args=args or {},
        status="trusted",
    )


@pytest.fixture
def mock_playbook(monkeypatch):
    pb = MagicMock()
    pb.state_signature.return_value = "sig-abc"
    pb.lookup_nav.return_value = _trusted_entry()
    pb.is_replay_allowed.return_value = True
    monkeypatch.setattr(unblock_learning, "_playbook", pb)
    return pb


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
        unblock_learning.unblock,
        "_has_identity_form",
        lambda _form: False,
    )
    return snap


def test_resolve_replay_when_trusted_entry_exists(
    mock_playbook, fake_snapshot, monkeypatch
):
    pb = mock_playbook
    page = _FakePage()
    job = {"title": "Engineer"}

    action, tier = unblock_learning.resolve_unblock_action(
        page,
        job,
        family="greenhouse",
        apex_host="boards.greenhouse.io",
    )

    assert tier == "replay"
    assert action == {"tool": "accept_cookies", "args": {}}
    pb.lookup_nav.assert_called_with("sig-abc", scope="host")
    pb.state_signature.assert_called_once()


def test_run_unblock_with_learning_skips_gemini_on_replay(
    mock_playbook, fake_snapshot, monkeypatch
):
    page = _FakePage()
    job = {"title": "Engineer"}
    monkeypatch.setattr(
        unblock_learning.extractor,
        "extract_fields",
        lambda _p: fake_snapshot["_form"],
    )
    monkeypatch.setattr(unblock_learning.unblock, "unblock_enabled", lambda: True)
    monkeypatch.setattr(unblock_learning.unblock, "_dismiss_cookies", lambda _p: False)
    monkeypatch.setattr(
        unblock_learning,
        "_state_advanced",
        lambda _before, _after: False,
    )
    monkeypatch.setattr(
        unblock_learning.unblock,
        "_execute",
        lambda _p, _a: "cookies",
    )

    with patch("applypilot.llm.get_gemini_client") as get_client:
        ok = unblock_learning.run_unblock_with_learning(
            page,
            job,
            family="greenhouse",
            apex_host="boards.greenhouse.io",
            max_steps=1,
        )
        get_client.assert_not_called()

    assert ok is False  # no identity form in fixture
    mock_playbook.bump_fail.assert_called()


def test_run_unblock_with_learning_records_used_state_sigs(
    mock_playbook, fake_snapshot, monkeypatch
):
    page = _FakePage()
    job = {"title": "Engineer"}
    used: list[str] = []
    monkeypatch.setattr(
        unblock_learning.extractor,
        "extract_fields",
        lambda _p: fake_snapshot["_form"],
    )
    monkeypatch.setattr(unblock_learning.unblock, "unblock_enabled", lambda: True)
    monkeypatch.setattr(unblock_learning.unblock, "_dismiss_cookies", lambda _p: False)
    monkeypatch.setattr(
        unblock_learning.unblock,
        "_execute",
        lambda _p, _a: "cookies",
    )

    # A step that does NOT advance must NOT be recorded for receipt credit.
    monkeypatch.setattr(
        unblock_learning, "_state_advanced", lambda _before, _after: False
    )
    unblock_learning.run_unblock_with_learning(
        page, job, family="greenhouse", apex_host="boards.greenhouse.io",
        max_steps=1, used_state_sigs=used,
    )
    assert used == []

    # A step that DOES advance is eligible for end-to-end stamp_verified credit.
    used_adv: list[str] = []
    monkeypatch.setattr(
        unblock_learning, "_state_advanced", lambda _before, _after: True
    )
    unblock_learning.run_unblock_with_learning(
        page, job, family="greenhouse", apex_host="boards.greenhouse.io",
        max_steps=1, used_state_sigs=used_adv,
    )
    assert used_adv == ["sig-abc"]


def test_submit_never_returned_from_replay_lookup(mock_playbook, fake_snapshot):
    mock_playbook.lookup_nav.return_value = _trusted_entry(
        tool="submit",
        args={},
    )
    page = _FakePage()
    job = {"title": "Engineer"}

    action, tier = unblock_learning.resolve_unblock_action(
        page,
        job,
        family="greenhouse",
        apex_host="boards.greenhouse.io",
    )

    assert action is None
    assert tier == "gemini"


def test_finish_never_returned_from_replay_lookup(mock_playbook, fake_snapshot):
    mock_playbook.lookup_nav.return_value = _trusted_entry(
        tool="finish",
        args={"status": "form_ready"},
    )
    page = _FakePage()

    action, tier = unblock_learning.resolve_unblock_action(
        page,
        {},
        family="greenhouse",
        apex_host="boards.greenhouse.io",
    )

    assert action is None
    assert tier == "gemini"
