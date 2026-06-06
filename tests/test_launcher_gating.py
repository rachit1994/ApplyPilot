"""Tests for launcher deterministic-only gating (W7)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from applypilot.apply import apply_budget, apply_settings


@pytest.fixture(autouse=True)
def reset_apply_settings():
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)
    yield
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)


def test_workday_runnable_in_deterministic_only():
    from applypilot.apply import launcher

    job = {
        "url": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Engineer",
        "application_url": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Engineer",
    }
    apply_settings.set_deterministic_only_override(True)
    assert launcher.job_runnable_in_deterministic_only(job) is True


def test_workday_runnable_without_deterministic_only_when_adapter_exists():
    from applypilot.apply import launcher

    job = {
        "url": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Engineer",
        "application_url": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Engineer",
    }
    apply_settings.set_deterministic_only_override(False)
    assert launcher.job_runnable_in_deterministic_only(job) is True


def test_icims_not_runnable_without_deterministic_only():
    from applypilot.apply import launcher

    job = {
        "url": "https://careers-acme.icims.com/jobs/12345/job",
        "application_url": "https://careers-acme.icims.com/jobs/12345/job",
    }
    apply_settings.set_deterministic_only_override(False)
    assert launcher.job_runnable_in_deterministic_only(job) is False


def test_try_direct_apply_workday_reaches_driver_in_deterministic_only(monkeypatch):
    from applypilot.apply import launcher
    from applypilot.apply.direct.driver import DriverResult

    apply_settings.set_deterministic_only_override(True)
    job = {
        "url": "https://example.com/job/1",
        "application_url": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Engineer",
    }
    monkeypatch.setattr(
        launcher,
        "_resolve_job_apply_url",
        lambda _job, persist=False: job["application_url"],
    )
    monkeypatch.setattr(
        "applypilot.apply.direct.throttle.check_caps",
        lambda *a, **k: (True, ""),
    )

    called: dict = {}

    def fake_apply_via_direct(*args, **kwargs):
        called["yes"] = True
        return DriverResult(result="applied", elapsed_ms=1, ats_family="workday")

    with patch(
        "applypilot.apply.direct.driver.apply_via_direct",
        side_effect=fake_apply_via_direct,
    ):
        monkeypatch.setattr(
            "applypilot.apply.direct.driver.apply_via_direct",
            fake_apply_via_direct,
        )
        result = launcher._try_direct_apply(
            job,
            port=9222,
            worker_id=0,
            dry_run=True,
        )

    assert called.get("yes") is True
    assert result is not None
    assert not str(result[0]).startswith("parked:needs_adapter")


def test_try_direct_apply_icims_defers_without_deterministic_only(monkeypatch):
    from applypilot.apply import launcher

    apply_settings.set_deterministic_only_override(False)
    apply_budget.governor().reset()
    job = {
        "url": "https://example.com/job/1",
        "application_url": "https://careers-acme.icims.com/jobs/12345/job",
    }
    monkeypatch.setattr(
        launcher,
        "_resolve_job_apply_url",
        lambda _job, persist=False: job["application_url"],
    )
    monkeypatch.setattr(
        launcher,
        "_park_job_needs_adapter",
        lambda url, detail: None,
    )

    with patch("applypilot.apply.direct.driver.apply_via_direct") as mock_driver:
        result = launcher._try_direct_apply(
            job,
            port=9222,
            worker_id=0,
            dry_run=True,
            defer_claude_rescue=True,
        )
        mock_driver.assert_not_called()

    assert result is not None
    assert str(result[0]).startswith("deferred:claude_rescue")
