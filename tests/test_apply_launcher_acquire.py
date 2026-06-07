from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def apply_db(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import database
    from applypilot.apply import launcher
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
    monkeypatch.setattr(launcher, "role_resumes_available", lambda: False)
    monkeypatch.setattr(config, "load_profile", lambda: {})
    launcher._stop_event.clear()

    def fake_ensure_resume_pdf(path: str | Path) -> Path:
        pdf = Path(path)
        if pdf.suffix.lower() != ".pdf":
            pdf = pdf.with_suffix(".pdf")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        if not pdf.exists():
            pdf.write_bytes(b"%PDF-1.4\n")
        return pdf.resolve()

    monkeypatch.setattr(launcher.prompt_mod, "ensure_resume_pdf", fake_ensure_resume_pdf)
    database.close_connection()
    conn = database.init_db()
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    yield conn
    database.close_connection()


def _insert_job(
    conn,
    url: str,
    *,
    title: str = "Ready Engineer",
    status: str | None = None,
    attempts: int | None = 0,
    last_attempted_at: str | None = None,
    application_url: str | None = None,
    site: str = "Example",
    full_description: str = "Build production systems.",
) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status,
            apply_attempts, last_attempted_at
        )
        VALUES (?, ?, ?, ?, '/tmp/resume.pdf', 9,
                ?, '$150K', ?, ?, ?)
        """,
        (
            url,
            title,
            site,
            application_url if application_url is not None else f"{url}/apply",
            full_description,
            status,
            attempts,
            last_attempted_at,
        ),
    )
    conn.commit()


def test_acquire_job_includes_ready_rows_with_null_apply_status(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import database
    from applypilot.apply import launcher
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
    monkeypatch.setattr(launcher, "role_resumes_available", lambda: False)
    monkeypatch.setattr(config, "load_profile", lambda: {})

    def fake_ensure_resume_pdf(path: str | Path) -> Path:
        pdf = Path(path)
        if pdf.suffix.lower() != ".pdf":
            pdf = pdf.with_suffix(".pdf")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        if not pdf.exists():
            pdf.write_bytes(b"%PDF-1.4\n")
        return pdf.resolve()

    monkeypatch.setattr(launcher.prompt_mod, "ensure_resume_pdf", fake_ensure_resume_pdf)
    database.close_connection()
    conn = database.init_db()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status, apply_attempts
        )
        VALUES (
            'https://jobs.example/ready', 'Ready Engineer', 'Example',
            'https://jobs.example/ready/apply', '/tmp/resume.pdf',
            9, 'Build production systems.', '$150K', NULL, 0
        )
        """
    )
    conn.commit()

    job = launcher.acquire_job(min_score=7, worker_id=0)

    assert job is not None
    assert job["url"] == "https://jobs.example/ready"
    row = conn.execute(
        "SELECT apply_status FROM jobs WHERE url = 'https://jobs.example/ready'"
    ).fetchone()
    assert row["apply_status"] == "in_progress"


def test_acquire_job_does_not_pick_submitted_unverified_until_retry(apply_db):
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://jobs.example/unverified",
        status="submitted_unverified",
    )

    assert launcher.acquire_job(min_score=7, worker_id=0) is None

    apply_db.execute(
        """
        UPDATE jobs
        SET apply_status = NULL, apply_error = NULL, applied_at = NULL
        WHERE url = 'https://jobs.example/unverified'
        """
    )
    apply_db.commit()

    job = launcher.acquire_job(min_score=7, worker_id=1)

    assert job is not None
    assert job["url"] == "https://jobs.example/unverified"


def test_acquire_job_continues_after_persisted_skip(apply_db, monkeypatch):
    from applypilot.apply import launcher
    from applypilot.apply.eligibility import ApplyDecision, EligibilityResult

    _insert_job(apply_db, "https://jobs.example/manual", title="AAA Manual")
    _insert_job(apply_db, "https://jobs.example/ready", title="ZZZ Ready")

    def fake_classify(job, **kwargs):
        if "manual" in job["url"]:
            return EligibilityResult(ApplyDecision.MANUAL, "manual ATS")
        return EligibilityResult(ApplyDecision.ELIGIBLE, None)

    monkeypatch.setattr(launcher, "classify_apply_target", fake_classify)

    job = launcher.acquire_job(min_score=7, worker_id=1)

    assert job is not None
    assert job["url"] == "https://jobs.example/ready"
    rows = apply_db.execute(
        "SELECT url, apply_status FROM jobs ORDER BY url"
    ).fetchall()
    assert [(r["url"], r["apply_status"]) for r in rows] == [
        ("https://jobs.example/manual", "manual"),
        ("https://jobs.example/ready", "in_progress"),
    ]


def test_acquire_job_prefers_fresh_direct_rows_over_parked_rows(apply_db):
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://authentication.example/apply",
        title="AAA Parked Generic",
        status="needs_adapter",
        application_url="https://authentication.example/apply",
    )
    _insert_job(
        apply_db,
        "https://job-boards.greenhouse.io/acme/jobs/123",
        title="ZZZ Fresh Greenhouse",
        status=None,
        application_url="https://job-boards.greenhouse.io/acme/jobs/123",
    )

    job = launcher.acquire_job(min_score=7, worker_id=0)

    assert job is not None
    assert job["url"] == "https://job-boards.greenhouse.io/acme/jobs/123"


def _patch_apply_engine_claude(monkeypatch):
    monkeypatch.setattr(
        "applypilot.apply.apply_settings.apply_engine",
        lambda **_: "claude",
    )


def test_worker_loop_retries_after_quota_reset_without_continuous(apply_db, monkeypatch):
    from applypilot.apply import launcher

    _patch_apply_engine_claude(monkeypatch)
    _insert_job(apply_db, "https://jobs.example/quota")
    not_before = (datetime.now(timezone.utc) + timedelta(milliseconds=20)).isoformat()
    calls: list[str] = []

    def fake_run_job(*args, **kwargs):
        calls.append("run")
        if len(calls) == 1:
            return f"failed:claude_quota_exhausted:{not_before}", 1, None
        return "applied", 1, None

    monkeypatch.setattr(launcher, "launch_chrome", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher, "run_job", fake_run_job)
    monkeypatch.setattr(launcher, "POLL_INTERVAL", 0.01)

    applied, failed = launcher.worker_loop(worker_id=0, limit=1, min_score=7)

    assert (applied, failed) == (1, 0)
    assert len(calls) == 2
    row = apply_db.execute(
        "SELECT apply_status, apply_not_before FROM jobs WHERE url = ?",
        ("https://jobs.example/quota",),
    ).fetchone()
    assert row["apply_status"] == "applied"
    assert row["apply_not_before"] is None


def test_release_stale_locks_releases_only_old_in_progress_rows(apply_db):
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://jobs.example/stale",
        status="in_progress",
        last_attempted_at="2000-01-01T00:00:00+00:00",
    )
    _insert_job(
        apply_db,
        "https://jobs.example/current",
        status="in_progress",
        last_attempted_at="2999-01-01T00:00:00+00:00",
    )

    assert launcher.release_stale_locks(max_age_minutes=45) == 1

    rows = {
        row["url"]: row["apply_status"]
        for row in apply_db.execute("SELECT url, apply_status FROM jobs").fetchall()
    }
    assert rows["https://jobs.example/stale"] is None
    assert rows["https://jobs.example/current"] == "in_progress"


def test_worker_loop_releases_lock_when_run_job_raises(apply_db, monkeypatch):
    from applypilot.apply import launcher

    _patch_apply_engine_claude(monkeypatch)
    _insert_job(apply_db, "https://jobs.example/raises")
    monkeypatch.setattr(launcher, "launch_chrome", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args, **kwargs: None)

    def raise_from_run_job(*args, **kwargs):
        raise RuntimeError("mock launcher failure")

    monkeypatch.setattr(launcher, "run_job", raise_from_run_job)

    applied, failed = launcher.worker_loop(limit=1, min_score=7)

    assert (applied, failed) == (0, 1)
    row = apply_db.execute(
        "SELECT apply_status, agent_id FROM jobs WHERE url = 'https://jobs.example/raises'"
    ).fetchone()
    assert row["apply_status"] is None
    assert row["agent_id"] is None


def test_worker_loop_failed_result_clears_lock_and_increments_attempts(apply_db, monkeypatch):
    from applypilot.apply import launcher

    _patch_apply_engine_claude(monkeypatch)
    _insert_job(apply_db, "https://jobs.example/fails")
    monkeypatch.setattr(launcher, "launch_chrome", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        launcher,
        "run_job",
        lambda *args, **kwargs: ("failed:mock_failure", 123, None),
    )

    applied, failed = launcher.worker_loop(limit=1, min_score=7)

    assert (applied, failed) == (0, 1)
    row = apply_db.execute(
        """
        SELECT apply_status, apply_error, apply_attempts, agent_id
        FROM jobs WHERE url = 'https://jobs.example/fails'
        """
    ).fetchone()
    assert row["apply_status"] == "failed"
    assert row["apply_error"] == "mock_failure"
    assert row["apply_attempts"] == 1
    assert row["agent_id"] is None


def test_mark_submitted_unverified_records_submission_time_and_clears_lock(apply_db):
    from applypilot.apply import launcher

    _insert_job(apply_db, "https://jobs.example/unverified", status="in_progress")

    launcher.mark_result(
        "https://jobs.example/unverified",
        "submitted_unverified",
        error="missing structured proof",
        duration_ms=456,
    )

    row = apply_db.execute(
        """
        SELECT apply_status, apply_error, applied_at, apply_attempts,
               apply_duration_ms, agent_id
        FROM jobs WHERE url = 'https://jobs.example/unverified'
        """
    ).fetchone()
    assert row["apply_status"] == "submitted_unverified"
    assert row["apply_error"] == "missing structured proof"
    assert row["applied_at"] is not None
    assert row["apply_attempts"] == 1
    assert row["apply_duration_ms"] == 456
    assert row["agent_id"] is None


def test_mark_result_failed_sets_retry_cooldown(apply_db):
    """A retryable failure parks the job with apply_not_before so the same job
    is not re-acquired in a tight continuous/overnight loop."""
    from applypilot.apply import launcher

    _insert_job(apply_db, "https://jobs.example/transient", status="in_progress")

    launcher.mark_result(
        "https://jobs.example/transient",
        "failed",
        error="direct_not_submitted",
        duration_ms=123,
    )

    row = apply_db.execute(
        """
        SELECT apply_status, apply_error, apply_attempts, apply_not_before, agent_id
        FROM jobs WHERE url = 'https://jobs.example/transient'
        """
    ).fetchone()
    assert row["apply_status"] == "failed"
    assert row["apply_error"] == "direct_not_submitted"
    assert row["apply_attempts"] == 1
    assert row["agent_id"] is None
    # Cooldown must be in the future so acquire_job's apply_not_before gate skips it.
    assert row["apply_not_before"] is not None
    not_before = datetime.fromisoformat(row["apply_not_before"])
    assert not_before > datetime.now(timezone.utc) + timedelta(hours=1)


def test_failed_job_with_cooldown_is_not_reacquired(apply_db):
    """After a failure, the same job is not handed out again until cooldown passes."""
    from applypilot.apply import launcher

    _insert_job(apply_db, "https://jobs.example/cooldown", status="in_progress")
    launcher.mark_result(
        "https://jobs.example/cooldown", "failed", error="direct_not_submitted"
    )

    # No other jobs exist -> queue should be empty (cooldown blocks re-acquire).
    assert launcher.acquire_job(min_score=7, worker_id=0) is None


def test_mark_result_permanent_failure_clears_cooldown(apply_db):
    """Permanent skips park hard at attempts=99 with no retry window."""
    from applypilot.apply import launcher

    _insert_job(apply_db, "https://jobs.example/permanent", status="in_progress")
    launcher.mark_result(
        "https://jobs.example/permanent",
        "failed",
        error="not_eligible_location",
        permanent=True,
    )

    row = apply_db.execute(
        "SELECT apply_attempts, apply_not_before FROM jobs "
        "WHERE url = 'https://jobs.example/permanent'"
    ).fetchone()
    assert row["apply_attempts"] == 99
    assert row["apply_not_before"] is None


def test_acquire_job_prefers_direct_adapter_before_linkedin(apply_db, monkeypatch):
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://jobs.example/linkedin",
        title="LinkedIn Role",
        application_url="https://www.linkedin.com/jobs/view/123",
        site="linkedin",
    )
    _insert_job(
        apply_db,
        "https://jobs.example/lever",
        title="Lever Role",
        application_url="https://jobs.lever.co/acme/uuid-1",
        site="lever:acme",
    )

    job = launcher.acquire_job(min_score=7, worker_id=0)

    assert job is not None
    assert job["url"] == "https://jobs.example/lever"


def test_wellfound_row_with_embedded_ats_url_is_direct_capable(apply_db):
    from applypilot.apply import launcher

    job = {
        "url": "https://wellfound.com/jobs/123",
        "application_url": "https://wellfound.com/jobs/123",
        "site": "Wellfound",
        "full_description": (
            "Apply through the employer ATS: "
            "https://jobs.lever.co/acme/uuid-123"
        ),
    }

    assert launcher.job_has_direct_adapter(job) is True
    assert job["application_url"] == "https://jobs.lever.co/acme/uuid-123"


def test_try_direct_apply_uses_recovered_wellfound_ats_url(apply_db, monkeypatch):
    from applypilot.apply import launcher
    from applypilot.apply.direct.driver import DriverResult

    _insert_job(
        apply_db,
        "https://wellfound.com/jobs/123",
        application_url="",
        site="Wellfound",
        full_description=(
            "External application: https://jobs.lever.co/acme/uuid-123"
        ),
    )
    job = {
        "url": "https://wellfound.com/jobs/123",
        "application_url": None,
        "site": "Wellfound",
        "full_description": (
            "External application: https://jobs.lever.co/acme/uuid-123"
        ),
    }
    seen: list[str] = []

    fake_dr = DriverResult(
        result="applied",
        elapsed_ms=50,
        escalate=False,
        ats_family="lever",
        fingerprint="lever:url",
    )

    class _ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target

        def start(self) -> None:
            if self._target:
                self._target()

        def join(self, timeout=None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    def fake_apply(job_arg, *args, **kwargs):
        seen.append(job_arg["application_url"])
        return fake_dr

    monkeypatch.setattr(launcher.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr("applypilot.apply.direct.driver.apply_via_direct", fake_apply)
    monkeypatch.setattr(
        "applypilot.apply.direct.throttle.check_caps",
        lambda *args, **kwargs: (True, None),
    )
    monkeypatch.setattr(
        launcher.apply_settings,
        "require_gmail_confirmation",
        lambda: False,
    )

    result = launcher._try_direct_apply(
        job, port=9222, worker_id=0, dry_run=True, defer_claude_rescue=True,
    )

    assert result is not None
    assert result[0] == "applied"
    assert seen == ["https://jobs.lever.co/acme/uuid-123"]
    row = apply_db.execute(
        "SELECT application_url FROM jobs WHERE url = ?",
        ("https://wellfound.com/jobs/123",),
    ).fetchone()
    assert row["application_url"] == "https://jobs.lever.co/acme/uuid-123"


def test_try_direct_apply_requires_gmail_receipt_for_applied(
    apply_db,
    monkeypatch,
):
    from types import SimpleNamespace

    from applypilot.apply import launcher
    from applypilot.apply.direct.driver import DriverResult

    _insert_job(
        apply_db,
        "https://jobs.example/lever",
        application_url="https://jobs.lever.co/acme/uuid-1",
    )
    job = {
        "url": "https://jobs.example/lever",
        "application_url": "https://jobs.lever.co/acme/uuid-1",
        "title": "Senior Engineer",
        "site": "ExampleCo",
    }
    fake_dr = DriverResult(
        result="applied",
        elapsed_ms=50,
        escalate=False,
        ats_family="lever",
        fingerprint="lever:url",
    )

    class _ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target

        def start(self) -> None:
            if self._target:
                self._target()

        def join(self, timeout=None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    recorded: list[str] = []
    monkeypatch.setattr(launcher.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        "applypilot.apply.direct.driver.apply_via_direct",
        lambda *args, **kwargs: fake_dr,
    )
    monkeypatch.setattr(
        "applypilot.apply.direct.throttle.check_caps",
        lambda *args, **kwargs: (True, None),
    )
    monkeypatch.setattr(
        launcher.apply_settings,
        "require_gmail_confirmation",
        lambda: True,
    )
    monkeypatch.setattr(
        "applypilot.apply.gmail_auth.wait_for_application_receipt",
        lambda _job, **kwargs: SimpleNamespace(
            confirmed=False,
            reason="gmail_receipt_not_found",
            message=None,
        ),
    )
    monkeypatch.setattr(
        "applypilot.database.record_apply_outcome",
        lambda **kwargs: recorded.append(kwargs["result"]),
    )

    result = launcher._try_direct_apply(
        job, port=9222, worker_id=0, dry_run=True, defer_claude_rescue=True,
    )

    assert result is not None
    assert result[0] == "submitted_unverified:gmail_receipt_not_found"
    assert recorded == ["submitted_unverified:gmail_receipt_not_found"]


def test_try_direct_apply_defers_claude_when_other_direct_jobs_remain(
    apply_db, monkeypatch,
):
    from applypilot.apply.direct.driver import DriverResult
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://jobs.example/gh-a",
        application_url="https://job-boards.greenhouse.io/a/jobs/1",
    )
    _insert_job(
        apply_db,
        "https://jobs.example/gh-b",
        application_url="https://job-boards.greenhouse.io/b/jobs/2",
    )

    job = {
        "url": "https://jobs.example/gh-a",
        "application_url": "https://job-boards.greenhouse.io/a/jobs/1",
    }

    fake_dr = DriverResult(
        result="failed:direct_partial_form",
        elapsed_ms=50,
        escalate=True,
        escalate_reason="partial_form",
        ats_family="greenhouse",
        fingerprint="greenhouse:url",
    )

    class _ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target

        def start(self) -> None:
            if self._target:
                self._target()

        def join(self, timeout=None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(launcher.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        "applypilot.apply.direct.driver.apply_via_direct",
        lambda *args, **kwargs: fake_dr,
    )
    monkeypatch.setattr(
        "applypilot.apply.direct.throttle.check_caps",
        lambda *args, **kwargs: (True, None),
    )
    monkeypatch.setattr(
        "applypilot.database.record_apply_outcome",
        lambda *args, **kwargs: None,
    )

    result = launcher._try_direct_apply(
        job, port=9222, worker_id=0, dry_run=True, defer_claude_rescue=True,
    )

    assert result is not None
    assert result[0].startswith("deferred:claude_rescue")
    row = apply_db.execute(
        "SELECT apply_error FROM jobs WHERE url = ?",
        (job["url"],),
    ).fetchone()
    assert row["apply_error"] is not None
    assert "pending_claude_rescue" in row["apply_error"]


def test_worker_loop_continues_after_each_failure(apply_db, monkeypatch):
    """One failed job must not stop the worker from processing the rest of the queue."""
    from applypilot.apply import launcher

    _patch_apply_engine_claude(monkeypatch)
    for i in range(3):
        _insert_job(apply_db, f"https://jobs.example/job-{i}")

    outcomes = iter(
        [
            ("failed:mock_failure", 1, None),
            ("applied", 2, None),
            ("failed:other_failure", 3, None),
        ]
    )

    def fake_run_pipeline(*args, **kwargs):
        return next(outcomes)

    monkeypatch.setattr(launcher, "launch_chrome", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        launcher, "_run_job_with_optional_fallback", fake_run_pipeline
    )
    monkeypatch.setattr(launcher, "count_acquirable_jobs", lambda **kwargs: 0)

    applied, failed = launcher.worker_loop(worker_id=0, limit=3, min_score=7)

    assert (applied, failed) == (1, 2)
    with pytest.raises(StopIteration):
        next(outcomes)


def test_should_defer_claude_rescue_false_for_pending_rescue_jobs(apply_db):
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://jobs.example/gh-peer",
        application_url="https://job-boards.greenhouse.io/acme/jobs/99",
    )
    rescue_job = {
        "url": "https://jobs.example/needs-claude",
        "application_url": "https://jobs.example/needs-claude/apply",
        "apply_error": "pending_claude_rescue:partial_form",
    }
    assert launcher._should_defer_claude_rescue(rescue_job, min_score=7) is False


def test_should_defer_claude_rescue_false_when_no_direct_adapter(apply_db):
    from applypilot.apply import launcher

    _insert_job(
        apply_db,
        "https://jobs.example/gh-peer",
        application_url="https://job-boards.greenhouse.io/acme/jobs/99",
    )
    no_adapter = {
        "url": "https://jobs.example/custom-ats",
        "application_url": "https://careers.example.com/role/1",
    }
    assert launcher.job_has_direct_adapter(no_adapter) is False
    assert launcher._should_defer_claude_rescue(no_adapter, min_score=7) is False


def test_park_job_for_retry_preserves_pending_claude_rescue_marker(apply_db):
    from applypilot.apply import launcher

    url = "https://jobs.example/rescue-quota"
    _insert_job(apply_db, url, status="in_progress")
    apply_db.execute(
        """
        UPDATE jobs
        SET apply_status = 'failed',
            apply_error = 'pending_claude_rescue:escalated'
        WHERE url = ?
        """,
        (url,),
    )
    apply_db.commit()
    not_before = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    launcher._park_job_for_retry(
        url,
        not_before=not_before,
        error=f"claude_quota_exhausted retry_after={not_before}",
    )
    row = apply_db.execute(
        "SELECT apply_error, apply_not_before FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row["apply_error"].startswith("pending_claude_rescue:")
    assert "quota_retry_after=" in row["apply_error"]
    assert row["apply_not_before"] == not_before


def test_pending_claude_rescue_runs_claude_when_other_direct_jobs_exist(
    apply_db, monkeypatch,
):
    """Quota-drained rescue jobs must not be deferred again while direct peers exist."""
    from applypilot.apply import launcher

    monkeypatch.setattr(
        "applypilot.apply.apply_settings.apply_engine",
        lambda **_: "direct",
    )
    _insert_job(
        apply_db,
        "https://jobs.example/gh-peer",
        application_url="https://job-boards.greenhouse.io/acme/jobs/99",
    )
    rescue = {
        "url": "https://jobs.example/custom",
        "title": "Custom ATS",
        "application_url": "https://careers.custom.example/apply/1",
        "apply_error": "pending_claude_rescue:partial_form",
    }
    claude_calls: list[str] = []

    def fake_run_job(job, **kwargs):
        claude_calls.append(job["url"])
        return "applied", 10, None

    monkeypatch.setattr(launcher, "run_job", fake_run_job)
    monkeypatch.setattr(
        "applypilot.apply.direct.throttle.check_caps",
        lambda *args, **kwargs: (True, None),
    )

    result, _, _ = launcher._run_job_with_optional_fallback(
        rescue,
        port=9222,
        worker_id=0,
        primary_model="haiku",
        dry_run=True,
        pace_seconds=0.0,
        confirm_submit=False,
        min_score=7,
    )

    assert result == "applied"
    assert claude_calls == [rescue["url"]]


def test_worker_retries_pending_claude_rescue_after_quota_window(apply_db, monkeypatch):
    from applypilot.apply import launcher

    _patch_apply_engine_claude(monkeypatch)
    url = "https://jobs.example/rescue-after-quota"
    _insert_job(
        apply_db,
        url,
        application_url="https://careers.custom.example/role/2",
    )
    apply_db.execute(
        """
        UPDATE jobs
        SET apply_status = 'failed',
            apply_error = 'pending_claude_rescue:escalated quota_retry_after=2099-01-01T00:00:00+00:00',
            apply_not_before = ?
        WHERE url = ?
        """,
        (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            url,
        ),
    )
    apply_db.commit()

    calls: list[str] = []

    def fake_run_job(job, **kwargs):
        calls.append("run")
        return "applied", 1, None

    monkeypatch.setattr(launcher, "launch_chrome", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher, "cleanup_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher, "run_job", fake_run_job)
    monkeypatch.setattr(launcher, "POLL_INTERVAL", 0.01)

    applied, failed = launcher.worker_loop(worker_id=0, limit=1, min_score=7)

    assert (applied, failed) == (1, 0)
    assert calls == ["run"]


def test_target_url_acquire_candidates_strips_apply_suffix():
    from applypilot.apply import launcher

    base = "https://jobs.lever.co/cscgeneration-2/d0df490d-99cd-4795-98aa-65ec290e95e0"
    exact, like = launcher._target_url_acquire_candidates(f"{base}/apply")
    assert base in exact
    assert f"{base}/apply" in exact
    assert like == f"{base}%"


def test_acquire_job_target_url_matches_apply_form_url(apply_db):
    from applypilot.apply import launcher

    base = "https://jobs.lever.co/cscgeneration-2/d0df490d-99cd-4795-98aa-65ec290e95e0"
    _insert_job(apply_db, base, application_url=f"{base}/apply")
    job = launcher.acquire_job(target_url=f"{base}/apply", worker_id=0)
    assert job is not None
    assert job["url"] == base


def test_explain_target_url_miss_applied_at_without_status(apply_db):
    from applypilot.apply import launcher

    url = "https://jobs.micro1.ai/post/abc123"
    _insert_job(apply_db, url)
    apply_db.execute(
        "UPDATE jobs SET applied_at = datetime('now') WHERE url = ?",
        (url,),
    )
    apply_db.commit()
    reason = launcher.explain_target_url_miss(url, include_untailored=True)
    assert reason is not None
    assert "applied_at" in reason
