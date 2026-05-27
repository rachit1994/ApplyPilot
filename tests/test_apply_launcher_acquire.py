from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def apply_db(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import database
    from applypilot.apply import launcher

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
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
    database.close_connection(db_path)
    conn = database.init_db(db_path)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    yield conn
    database.close_connection(db_path)


def _insert_job(
    conn,
    url: str,
    *,
    title: str = "Ready Engineer",
    status: str | None = None,
    attempts: int | None = 0,
    last_attempted_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status,
            apply_attempts, last_attempted_at
        )
        VALUES (?, ?, 'Example', ?, '/tmp/resume.pdf', 9,
                'Build production systems.', '$150K', ?, ?, ?)
        """,
        (url, title, f"{url}/apply", status, attempts, last_attempted_at),
    )
    conn.commit()


def test_acquire_job_includes_ready_rows_with_null_apply_status(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import database
    from applypilot.apply import launcher

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(launcher, "_load_blocked", lambda: (set(), []))
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
    database.close_connection(db_path)
    conn = database.init_db(db_path)
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


def test_worker_loop_retries_after_quota_reset_without_continuous(apply_db, monkeypatch):
    from applypilot.apply import launcher

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
