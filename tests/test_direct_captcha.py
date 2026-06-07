"""Unit tests for direct CapSolver captcha helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from applypilot.apply import prompt_scripts
from applypilot.apply.direct import captcha as direct_captcha


def test_captcha_detect_eval_js_is_valid_javascript():
    js = prompt_scripts.captcha_detect_eval_js()
    assert "{{" not in js
    assert "}} " not in js
    assert "() => {" in js


def test_captcha_inject_hcaptcha_eval_js_escapes_token():
    js = prompt_scripts.captcha_inject_hcaptcha_eval_js("tok'en\\x")
    assert "tok\\'en\\\\x" in js
    assert "{{" not in js


def test_detect_captcha_uses_eval_js():
    page = MagicMock()
    page.evaluate.return_value = {"type": "hcaptcha", "sitekey": "abc", "url": "https://x"}
    info = direct_captcha.detect_captcha(page)
    page.evaluate.assert_called_once()
    called_js = page.evaluate.call_args[0][0]
    assert "{{" not in called_js
    assert info and info["type"] == "hcaptcha"


def test_solve_captcha_if_present_no_captcha():
    page = MagicMock()
    with patch.object(direct_captcha, "detect_captcha", return_value=None):
        assert direct_captcha.solve_captcha_if_present(page, api_key="key") is True


def test_solve_captcha_if_present_skips_recaptchav3():
    page = MagicMock()
    with patch.object(
        direct_captcha,
        "detect_captcha_blocking",
        return_value={"type": "recaptchav3", "sitekey": "x", "url": "https://x"},
    ):
        assert direct_captcha.solve_captcha_if_present(page, api_key="key") is True


def test_detect_captcha_blocking_enriches_workable_sitekey():
    page = MagicMock()
    page.evaluate.side_effect = [
        {"type": "turnstile_script_only", "url": "https://apply.workable.com/x/apply/"},
        "0x4AAAAAAAVY8hH3nz6RxaK0",
    ]
    info = direct_captcha.detect_captcha_blocking(page, wait_s=0)
    assert info
    assert info["type"] == "turnstile"
    assert info["sitekey"] == "0x4AAAAAAAVY8hH3nz6RxaK0"


def test_solve_captcha_if_present_turnstile_script_only_with_wall():
    page = MagicMock()
    with patch.object(
        direct_captcha,
        "detect_captcha_blocking",
        return_value={"type": "turnstile_script_only", "url": "https://x"},
    ), patch.object(
        direct_captcha,
        "detect_captcha",
        return_value={"type": "turnstile_script_only", "url": "https://x"},
    ), patch.object(direct_captcha, "turnstile_wall_visible", return_value=True):
        assert direct_captcha.solve_captcha_if_present(page, api_key="key") is False


def test_solve_captcha_if_present_hcaptcha_without_key():
    page = MagicMock()
    with patch.object(
        direct_captcha,
        "detect_captcha",
        return_value={"type": "hcaptcha", "sitekey": "sk", "url": "https://jobs.lever.co/x"},
    ):
        assert direct_captcha.solve_captcha_if_present(page, api_key="") is False


@patch.object(direct_captcha.apply_settings, "captcha_solving_enabled", return_value=True)
@patch.object(direct_captcha, "_inject_token", return_value=True)
@patch.object(direct_captcha, "_poll_task", return_value="solved-token")
@patch.object(direct_captcha, "_create_task", return_value="task-1")
def test_solve_captcha_if_present_hcaptcha_happy_path(
    mock_create: MagicMock,
    mock_poll: MagicMock,
    mock_inject: MagicMock,
    _mock_enabled: MagicMock,
):
    page = MagicMock()
    page.url = "https://jobs.lever.co/acceldata/job"
    with patch.object(
        direct_captcha,
        "detect_captcha_blocking",
        return_value={"type": "hcaptcha", "sitekey": "site-key", "url": page.url},
    ):
        ok = direct_captcha.solve_captcha_if_present(page, api_key="capsolver-key")
    assert ok is True
    mock_create.assert_called_once_with(
        "capsolver-key",
        task_type="HCaptchaTaskProxyLess",
        sitekey="site-key",
        page_url=page.url,
        metadata=None,
    )
    mock_poll.assert_called_once_with("capsolver-key", "task-1")
    mock_inject.assert_called_once_with(page, "hcaptcha", "solved-token")


def test_solution_token_prefers_grecaptcha_response():
    assert direct_captcha._solution_token({"gRecaptchaResponse": "a", "token": "b"}) == "a"
    assert direct_captcha._solution_token({"token": "b"}) == "b"


@patch.object(direct_captcha.apply_settings, "captcha_solving_enabled", return_value=True)
@patch.object(direct_captcha, "_inject_token", return_value=True)
@patch.object(direct_captcha, "_poll_task", return_value="solved-token")
@patch.object(direct_captcha, "_create_task", return_value="task-1")
def test_solve_captcha_if_present_turnstile_happy_path(
    mock_create: MagicMock,
    mock_poll: MagicMock,
    mock_inject: MagicMock,
    _mock_enabled: MagicMock,
):
    page = MagicMock()
    page.url = "https://apply.workable.com/co/j/abc/apply/"
    info = {
        "type": "turnstile",
        "sitekey": "0x4AAAA",
        "url": page.url,
        "action": "managed",
    }
    with patch.object(direct_captcha, "detect_captcha_blocking", return_value=info):
        ok = direct_captcha.solve_captcha_if_present(page, api_key="capsolver-key")
    assert ok is True
    mock_create.assert_called_once_with(
        "capsolver-key",
        task_type="AntiTurnstileTaskProxyLess",
        sitekey="0x4AAAA",
        page_url=page.url,
        metadata={"action": "managed"},
    )


def test_detect_captcha_blocking_waits_for_turnstile_widget():
    page = MagicMock()
    script_only = {"type": "turnstile_script_only", "note": "Wait 3s and re-detect."}
    widget = {"type": "turnstile", "sitekey": "0x4", "url": "https://x"}
    with patch.object(
        direct_captcha,
        "detect_captcha",
        side_effect=[script_only, widget],
    ), patch.object(
        direct_captcha,
        "_enrich_turnstile_info",
        side_effect=lambda _page, info: info,
    ):
        info = direct_captcha.detect_captcha_blocking(page, wait_s=0.01)
    assert info == widget
    page.wait_for_timeout.assert_called_once()


def test_is_blocking_captcha():
    assert direct_captcha.is_blocking_captcha({"type": "turnstile", "sitekey": "x"})
    assert not direct_captcha.is_blocking_captcha({"type": "turnstile_script_only"})
    assert not direct_captcha.is_blocking_captcha({"type": "recaptchav3"})
    assert not direct_captcha.is_blocking_captcha(None)


@pytest.mark.parametrize("ctype", ["funcaptcha"])
def test_solve_captcha_if_present_unsupported_types(ctype: str):
    page = MagicMock()
    with patch.object(
        direct_captcha,
        "detect_captcha_blocking",
        return_value={"type": ctype, "sitekey": "sk", "url": "https://x"},
    ):
        assert direct_captcha.solve_captcha_if_present(page, api_key="key") is False
