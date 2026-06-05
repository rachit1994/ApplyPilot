"""Tests for apply/direct/actions.py dispatch and detect_advanced."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from applypilot.apply.direct import actions as act


def _page_mock() -> MagicMock:
    page = MagicMock()
    page.url = "https://jobs.example.com/apply"
    page.wait_for_timeout = MagicMock()
    page.goto = MagicMock()
    return page


def test_click_dispatch_success():
    page = _page_mock()
    with patch.object(act, "_click_text", return_value=True) as click:
        result = act.execute(page, {"tool": "click", "args": {"text": "Apply now"}})
    click.assert_called_once_with(page, "Apply now")
    assert result.outcome == "clicked"
    assert result.error is None


def test_click_dispatch_miss():
    page = _page_mock()
    with patch.object(act, "_click_text", return_value=False):
        result = act.execute(page, {"tool": "click", "args": {"text": "Missing"}})
    assert result.outcome == "click_miss"


def test_accept_cookies_dispatch_success():
    page = _page_mock()
    with patch.object(act, "_dismiss_cookies", return_value=True) as dismiss:
        result = act.execute(page, {"tool": "accept_cookies", "args": {}})
    dismiss.assert_called_once_with(page)
    assert result.outcome == "cookies"


def test_accept_cookies_dispatch_miss():
    page = _page_mock()
    with patch.object(act, "_dismiss_cookies", return_value=False):
        result = act.execute(page, {"tool": "accept_cookies", "args": {}})
    assert result.outcome == "cookies_miss"


def test_goto_allowlist_blocks_off_site_url():
    page = _page_mock()
    ctx = act.ActionContext(goto_allowlist=frozenset({"greenhouse.io"}))
    result = act.execute(
        page,
        {"tool": "goto", "args": {"url": "https://evil.example/phish"}},
        context=ctx,
    )
    assert result.outcome == "goto_blocked"
    assert result.error == "url not in goto_allowlist"
    page.goto.assert_not_called()


def test_goto_allowlist_allows_matching_host():
    page = _page_mock()
    ctx = act.ActionContext(goto_allowlist=frozenset({"boards.greenhouse.io"}))
    result = act.execute(
        page,
        {"tool": "goto", "args": {"url": "https://boards.greenhouse.io/acme/jobs/1"}},
        context=ctx,
    )
    assert result.outcome == "navigated"
    page.goto.assert_called_once()


def test_login_provider_aliases_google():
    page = _page_mock()
    with patch.object(act, "_click_any", return_value=True) as click_any:
        result = act.execute(page, {"tool": "login_provider", "args": {"name": "google"}})
    click_any.assert_called_once()
    assert result.outcome == "google"


def test_next_page_clicks_known_advance_text():
    page = _page_mock()
    with patch.object(act, "_click_text", side_effect=lambda _p, text: text == "Continue") as click:
        result = act.execute(page, {"tool": "next_page", "args": {"texts": ["Next", "Continue"]}})
    assert result.outcome == "next_page"
    assert result.advanced is True
    assert click.call_count == 2


def test_wait_for_form_returns_ready_when_identity_form_appears():
    page = _page_mock()
    form = MagicMock()
    with (
        patch.object(act.extractor, "extract_fields", return_value=form),
        patch.object(act, "_has_identity_form", return_value=True),
    ):
        result = act.execute(page, {"tool": "wait_for_form", "args": {"timeout_ms": 500}})
    assert result.outcome == "form_ready"
    assert result.advanced is True


def test_detect_advanced_field_count_increased():
    before = {"fields": [{"label": "Email"}], "has_password_field": False}
    after = {"fields": [{"label": "Email"}, {"label": "Phone"}], "has_password_field": False}
    assert act.detect_advanced(before, after) is True


def test_detect_advanced_login_cleared():
    before = {"fields": [], "has_password_field": True}
    after = {"fields": [], "has_password_field": False}
    assert act.detect_advanced(before, after) is True


def test_detect_advanced_identity_form_appeared():
    before = {
        "fields": [{"label": "Subscribe"}],
        "has_password_field": False,
    }
    after = {
        "fields": [
            {"label": "First name"},
            {"label": "Email"},
            {"label": "Phone"},
        ],
        "has_password_field": False,
    }
    assert act.detect_advanced(before, after) is True


def test_detect_advanced_no_change():
    snap = {"fields": [{"label": "Email"}], "has_password_field": False}
    assert act.detect_advanced(snap, snap) is False


def test_side_effecting_and_never_cache_sets():
    assert "click" in act.SIDE_EFFECTING_TOOLS
    assert "goto" in act.SIDE_EFFECTING_TOOLS
    assert "submit" in act.NEVER_CACHE_TOOLS
    assert "submit" not in act.ACTION_VOCABULARY
