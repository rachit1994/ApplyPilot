"""Tests for apply URL visit ledger (dedup / re-apply loop prevention)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from applypilot.apply import visit_ledger
from applypilot.database import get_connection, init_db, record_apply_outcome


@pytest.fixture(autouse=True)
def reset_apply_globals():
    from applypilot.apply import apply_budget, apply_settings, launcher

    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)
    launcher._stop_event.clear()
    yield
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)
    launcher._stop_event.clear()


@pytest.fixture
def apply_db(tmp_path: Path, monkeypatch):
    from applypilot import config
    from applypilot import database

    db_path = tmp_path / "applypilot.db"
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.close_connection(db_path)
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    database.close_connection(db_path)


def test_canonical_apply_url_strips_query_and_trailing_slash():
    raw = "https://Apply.Workable.com/covergo/j/ABC123/apply/?ref=1"
    assert visit_ledger.canonical_apply_url(raw) == (
        "apply.workable.com/covergo/j/ABC123/apply"
    )


def test_visit_should_skip_after_recent_failure(apply_db, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_VISIT_REPEAT_MINUTES", "120")
    apply_url = "https://apply.workable.com/covergo/j/ED7B412F0D/apply/"
    record_apply_outcome(
        conn=apply_db,
        url=apply_url,
        result="failed:direct_not_submitted",
        ats_family="workable",
    )
    skip, reason, visit = visit_ledger.visit_should_skip(apply_url, conn=apply_db)
    assert skip is True
    assert reason is not None
    assert "recent_visit" in reason
    assert visit is not None


def test_visit_should_skip_after_success(apply_db):
    apply_url = "https://apply.workable.com/covergo/j/ED7B412F0D/apply/"
    record_apply_outcome(
        conn=apply_db,
        url=apply_url,
        result="applied",
        ats_family="workable",
    )
    skip, reason, _visit = visit_ledger.visit_should_skip(apply_url, conn=apply_db)
    assert skip is True
    assert reason is not None
    assert "already_applied" in reason


def test_visit_allows_retry_after_cooldown(apply_db, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_VISIT_REPEAT_MINUTES", "30")
    apply_url = "https://apply.workable.com/covergo/j/ED7B412F0D/apply/"
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    record_apply_outcome(
        conn=apply_db,
        url=apply_url,
        result="failed:direct_not_submitted",
        ats_family="workable",
        created_at=old,
    )
    skip, _reason, _visit = visit_ledger.visit_should_skip(apply_url, conn=apply_db)
    assert skip is False


def test_park_job_needs_adapter_sets_cooldown(apply_db, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_RETRY_COOLDOWN_HOURS", "4")
    from applypilot.apply import launcher

    job_url = "https://jobs.example.com/1"
    apply_db.execute(
        """
        INSERT INTO jobs (url, title, site, fit_score, tailored_resume_path)
        VALUES (?, 'Engineer', 'Example', 8, 'resume.pdf')
        """,
        (job_url,),
    )
    apply_db.commit()
    launcher._park_job_needs_adapter(job_url, "unresolved_required")
    row = apply_db.execute(
        "SELECT apply_status, apply_not_before, apply_error FROM jobs WHERE url = ?",
        (job_url,),
    ).fetchone()
    assert row["apply_status"] == "needs_adapter"
    assert row["apply_not_before"] is not None
    assert row["apply_error"] == "unresolved_required"


def test_acquire_skips_recent_visit(apply_db, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_VISIT_REPEAT_MINUTES", "120")
    from applypilot.apply import apply_settings, launcher

    apply_settings.set_deterministic_only_override(True)
    job_url = "https://jobs.example.com/covergo"
    apply_url = "https://apply.workable.com/covergo/j/ED7B412F0D/apply/"
    apply_db.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, tailored_resume_path, application_url
        )
        VALUES (?, 'Lead Full Stack Engineer', 'Workable', 8, 'resume.pdf', ?)
        """,
        (job_url, apply_url),
    )
    apply_db.commit()
    record_apply_outcome(
        conn=apply_db,
        url=apply_url,
        result="failed:direct_not_submitted",
        ats_family="workable",
    )
    monkeypatch.setattr(launcher, "role_resumes_available", lambda: True)
    monkeypatch.setattr(
        launcher.prompt_mod,
        "ensure_resume_pdf",
        lambda _path: None,
    )
    acquired = launcher.acquire_job(min_score=0, include_untailored=True)
    assert acquired is None
    row = apply_db.execute(
        "SELECT apply_not_before, apply_error FROM jobs WHERE url = ?",
        (job_url,),
    ).fetchone()
    assert row["apply_not_before"] is not None
    assert "apply_visit" in (row["apply_error"] or "")
