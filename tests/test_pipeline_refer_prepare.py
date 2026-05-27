"""Pipeline refer stage runs prepare-only (no OpenOutreach connect/message)."""

from unittest.mock import MagicMock, patch

from applypilot.pipeline import _run_refer


def test_run_refer_calls_prepare_only():
    settings = MagicMock()
    settings.enabled = True
    with patch("applypilot.outreach.config.load_outreach_config", return_value=settings):
        with patch(
            "applypilot.outreach.pipeline.run_referral_prepare",
            return_value={"scrape": {"scraped": 1}, "draft": {"drafted": 1}},
        ) as prepare:
            with patch("applypilot.outreach.pipeline.run_referral_send") as send:
                result = _run_refer()
    prepare.assert_called_once()
    send.assert_not_called()
    assert result["status"] == "ok"
