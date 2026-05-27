"""Apply queue preflight: acquirable counts and reset-failed behavior."""

from __future__ import annotations

from pathlib import Path

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
    database.close_connection(db_path)
    conn = database.init_db(db_path)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    yield conn
    database.close_connection(db_path)


def _insert_ready(conn, url: str, *, attempts: int = 0, status: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status, apply_attempts
        )
        VALUES (?, 'Engineer', 'Coast', ?, '/tmp/resume.pdf', 8,
                'Build systems.', '$150K', ?, ?)
        """,
        (url, f"{url}/apply", status, attempts),
    )
    conn.commit()


def test_count_acquirable_excludes_jobs_not_before_future(apply_db):
    from applypilot.apply.launcher import count_acquirable_jobs

    conn = apply_db
    _insert_ready(conn, "https://jobs.example/ready")
    _insert_ready(conn, "https://jobs.example/parked", status=None, attempts=0)
    conn.execute(
        "UPDATE jobs SET apply_not_before = datetime('now', '+2 hours') WHERE url = ?",
        ("https://jobs.example/parked",),
    )
    conn.commit()

    assert count_acquirable_jobs(min_score=0) == 1


def test_count_acquirable_excludes_in_progress_and_exhausted_failed(apply_db):
    from applypilot.apply.launcher import count_acquirable_jobs

    conn = apply_db
    _insert_ready(conn, "https://jobs.example/ready")
    _insert_ready(conn, "https://jobs.example/inprog", status="in_progress", attempts=1)
    _insert_ready(conn, "https://jobs.example/exhausted", status="failed", attempts=3)

    assert count_acquirable_jobs(min_score=0) == 1


def test_reset_failed_includes_exhausted_attempts(apply_db):
    from applypilot.apply.launcher import count_acquirable_jobs, reset_failed

    conn = apply_db
    _insert_ready(conn, "https://jobs.example/exhausted", status="failed", attempts=3)
    _insert_ready(conn, "https://jobs.example/permanent", status="failed", attempts=99)

    assert count_acquirable_jobs(min_score=0) == 0
    reset = reset_failed()
    assert reset == 1
    assert count_acquirable_jobs(min_score=0) == 1


def test_quota_retry_timestamp_preserves_iso_colons_and_reopens_after_reset(apply_db, monkeypatch):
    from applypilot.apply import launcher
    from applypilot.apply.launcher import count_acquirable_jobs

    conn = apply_db
    _insert_ready(conn, "https://jobs.example/quota", status="failed", attempts=0)
    not_before = "2026-05-27T10:00:00+00:00"

    reason, detail = launcher._parse_worker_result(
        f"failed:claude_quota_exhausted:{not_before}"
    )
    assert reason == "claude_quota_exhausted"
    assert detail == not_before

    launcher._park_job_for_retry(
        "https://jobs.example/quota",
        not_before=detail,
        error=f"claude_quota_exhausted retry_after={detail}",
    )
    row = conn.execute(
        "SELECT apply_not_before FROM jobs WHERE url = ?",
        ("https://jobs.example/quota",),
    ).fetchone()
    assert row["apply_not_before"] == not_before

    assert count_acquirable_jobs(min_score=0) == 0
    conn.execute(
        "UPDATE jobs SET apply_not_before = datetime('now', '-1 minute') WHERE url = ?",
        ("https://jobs.example/quota",),
    )
    conn.commit()
    assert count_acquirable_jobs(min_score=0) == 1


def test_repair_invalid_quota_retry_window_makes_job_acquirable(apply_db):
    from applypilot.apply import launcher

    url = "https://jobs.example/quota-truncated"
    _insert_ready(apply_db, url, status="failed", attempts=0)
    apply_db.execute(
        """
        UPDATE jobs
        SET apply_error = 'claude_quota_exhausted retry_after=2026-05-27T10',
            apply_not_before = '2026-05-27T10'
        WHERE url = ?
        """,
        (url,),
    )
    apply_db.commit()

    assert launcher.count_acquirable_jobs(min_score=0) == 0
    assert launcher.repair_invalid_quota_retry_windows() == 1

    row = apply_db.execute(
        "SELECT apply_not_before, apply_error FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row["apply_not_before"] is None
    assert "retry window repaired" in row["apply_error"]
    assert launcher.count_acquirable_jobs(min_score=0) == 1
