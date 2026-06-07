"""Tests for manual-review parking (bot protection / human-only walls)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from applypilot.apply import apply_budget, apply_settings
from applypilot.apply.direct.driver import DriverResult
from applypilot.database import get_connection, init_db


@pytest.fixture(autouse=True)
def reset_apply_settings():
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)
    yield
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)


@pytest.fixture
def apply_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    init_db()
    conn = get_connection()
    url = "https://jobs.example.com/apply/1"
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, fit_score, tailored_resume_path)
        VALUES (?, 'Engineer', 'Example', 8, 'resume.pdf')
        """,
        (url,),
    )
    conn.commit()
    return url


def test_manual_review_reason_detects_captcha():
    from applypilot.apply import launcher

    assert launcher._manual_review_reason(
        "failed:direct_needs_verification",
        "captcha_unsolved",
    ) == "captcha_unsolved"


def test_manual_review_reason_detects_escalation_cap():
    from applypilot.apply import launcher

    reason = launcher._manual_review_reason(
        "failed:direct_escalation_cap",
        "escalation_cap:workday fail_rate=1.00 attempts=6",
    )
    assert reason is not None
    assert "escalation_cap" in reason


def test_manual_review_reason_ignores_email_verify():
    from applypilot.apply import launcher

    assert launcher._manual_review_reason(
        "failed:direct_needs_verification",
        "email_verification_code",
    ) is None


def test_park_job_manual_review_sets_status(apply_db):
    from applypilot.apply import launcher

    launcher._park_job_manual_review(apply_db, "captcha_unsolved")
    row = get_connection().execute(
        "SELECT apply_status, apply_error FROM jobs WHERE url = ?",
        (apply_db,),
    ).fetchone()
    assert row["apply_status"] == "manual"
    assert row["apply_error"] == "captcha_unsolved"


def test_try_direct_apply_parks_captcha_as_manual(apply_db, monkeypatch):
    from applypilot.apply import launcher

    apply_settings.set_deterministic_only_override(True)
    job = {
        "url": apply_db,
        "application_url": "https://boards.greenhouse.io/acme/jobs/1",
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

    dr = DriverResult(
        result="failed:direct_needs_verification",
        escalate=True,
        escalate_reason="captcha_unsolved",
        elapsed_ms=5,
        ats_family="greenhouse",
    )

    with patch(
        "applypilot.apply.direct.driver.apply_via_direct",
        return_value=dr,
    ):
        result = launcher._try_direct_apply(
            job,
            port=9222,
            worker_id=0,
            dry_run=True,
        )

    assert result is not None
    assert str(result[0]).startswith("parked:manual:")
    row = get_connection().execute(
        "SELECT apply_status, apply_error FROM jobs WHERE url = ?",
        (apply_db,),
    ).fetchone()
    assert row["apply_status"] == "manual"
    assert "captcha" in row["apply_error"]


def test_acquire_job_skips_manual_in_queue(apply_db):
    from applypilot.apply import launcher

    launcher._park_job_manual_review(apply_db, "bot_protection")
    job = launcher.acquire_job(worker_id=0, include_untailored=True)
    assert job is None


def test_requeue_manual_reopens_queue(apply_db):
    from applypilot.apply import launcher

    launcher._park_job_manual_review(apply_db, "captcha_unsolved")
    assert launcher.requeue_manual(reason_contains="captcha") == 1
    row = get_connection().execute(
        "SELECT apply_status, apply_error FROM jobs WHERE url = ?",
        (apply_db,),
    ).fetchone()
    assert row["apply_status"] is None
    assert row["apply_error"] is None
    job = launcher.acquire_job(worker_id=0, include_untailored=True)
    assert job is not None
    assert job["url"] == apply_db


def test_requeue_manual_reason_filter_misses(apply_db):
    from applypilot.apply import launcher

    launcher._park_job_manual_review(apply_db, "sso_login_needed")
    assert launcher.requeue_manual(reason_contains="captcha") == 0
    row = get_connection().execute(
        "SELECT apply_status FROM jobs WHERE url = ?",
        (apply_db,),
    ).fetchone()
    assert row["apply_status"] == "manual"


def test_manual_review_reason_detects_no_application_form():
    from applypilot.apply import launcher

    reason = launcher._manual_review_reason(
        "failed:direct_no_application_form",
        "no_application_form",
    )
    assert reason is not None
    assert "application" in reason.lower()


def test_manual_review_reason_detects_no_confirmation():
    from applypilot.apply import launcher

    reason = launcher._manual_review_reason(
        "failed:direct_not_submitted",
        "no_confirmation",
    )
    assert reason == "no_confirmation"


def test_deterministic_manual_park_no_confirmation():
    from applypilot.apply import apply_settings, launcher

    apply_settings.set_deterministic_only_override(True)
    reason = launcher._deterministic_manual_park_reason(
        "failed:direct_not_submitted",
        "no_confirmation",
        apply_url="https://jobs.lever.co/acme/apply",
    )
    assert reason == "no_confirmation"


def test_deterministic_manual_park_oracle_host():
    from applypilot.apply import apply_settings, launcher

    apply_settings.set_deterministic_only_override(True)
    reason = launcher._deterministic_manual_park_reason(
        "failed:direct_no_form",
        "no_form",
        apply_url="https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/job/1",
    )
    assert reason == "no_form"


def test_acquire_skips_needs_adapter_in_deterministic_only(apply_db, monkeypatch):
    from applypilot.apply import apply_settings, launcher
    from applypilot.database import get_connection

    apply_settings.set_deterministic_only_override(True)
    conn = get_connection()
    blocked_url = apply_db
    conn.execute(
        """
        UPDATE jobs SET apply_status = 'needs_adapter', apply_error = 'no_confirmation',
               application_url = ?
        WHERE url = ?
        """,
        (f"{blocked_url}/apply", blocked_url),
    )
    conn.commit()
    ready_url = "https://jobs.lever.co/other/j/2"
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, application_url, tailored_resume_path,
                          fit_score, full_description, salary)
        VALUES (?, 'Other', 'Lever', ?, '/tmp/resume.pdf', 9, 'desc', '$1')
        """,
        (ready_url, f"{ready_url}/apply"),
    )
    conn.commit()
    monkeypatch.setattr(apply_settings, "apply_engine", lambda: "direct")
    job = launcher.acquire_job(worker_id=0, include_untailored=True)
    assert job is not None
    assert job["url"] == ready_url


def test_acquire_retries_needs_adapter_unresolved_required(apply_db, monkeypatch):
    from applypilot.apply import apply_settings, launcher
    from applypilot.database import get_connection

    apply_settings.set_deterministic_only_override(True)
    conn = get_connection()
    workable_url = "https://apply.workable.com/acme/j/ABC/apply/"
    conn.execute(
        """
        UPDATE jobs SET url = ?, application_url = ?, apply_status = 'needs_adapter',
               apply_error = 'unresolved_required', site = 'Workable', fit_score = 8
        WHERE url = ?
        """,
        (workable_url, workable_url, apply_db),
    )
    conn.commit()
    monkeypatch.setattr(apply_settings, "apply_engine", lambda: "direct")
    job = launcher.acquire_job(worker_id=0, include_untailored=True)
    assert job is not None
    assert job["url"] == workable_url


def test_acquire_parks_oracle_host_in_deterministic_only(apply_db, monkeypatch):
    from applypilot.apply import apply_settings, launcher
    from applypilot.database import get_connection

    apply_settings.set_deterministic_only_override(True)
    conn = get_connection()
    conn.execute("DELETE FROM jobs WHERE url = ?", (apply_db,))
    oracle_url = (
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/1"
    )
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, application_url, tailored_resume_path,
                          fit_score, full_description, salary)
        VALUES (?, 'JPM SE', 'JPM', ?, '/tmp/resume.pdf', 8, 'desc', '$1')
        """,
        (oracle_url, oracle_url),
    )
    conn.commit()
    monkeypatch.setattr(apply_settings, "apply_engine", lambda: "direct")
    assert launcher.acquire_job(worker_id=0, include_untailored=True) is None
    row = conn.execute(
        "SELECT apply_status, apply_error FROM jobs WHERE url = ?",
        (oracle_url,),
    ).fetchone()
    assert row["apply_status"] == "manual"
    assert row["apply_error"] == "oracle_hcm_unsupported"


def test_requeue_needs_adapter_reopens_queue(apply_db):
    from applypilot.apply import launcher

    conn = get_connection()
    conn.execute(
        """
        UPDATE jobs SET apply_status = 'needs_adapter',
               apply_error = 'submit_rejected:Something went wrong'
        WHERE url = ?
        """,
        (apply_db,),
    )
    conn.commit()
    assert launcher.requeue_needs_adapter(reason_contains="Something went wrong") == 1
    row = conn.execute(
        "SELECT apply_status, apply_error FROM jobs WHERE url = ?",
        (apply_db,),
    ).fetchone()
    assert row["apply_status"] is None
    assert row["apply_error"] is None

