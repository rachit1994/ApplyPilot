"""Tests for prepare → review → submit apply workflow."""

from __future__ import annotations

import json
from pathlib import Path

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
    status: str | None = None,
    tailored: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, apply_status
        )
        VALUES (?, 'Engineer', 'Example', ?, ?, 9, 'Build things.', ?)
        """,
        (
            url,
            f"{url}/apply",
            "/tmp/resume.pdf" if tailored else None,
            status,
        ),
    )
    conn.commit()


def test_mark_prepare_review_sets_status_and_form(apply_db):
    from applypilot.apply import launcher

    url = "https://jobs.example.com/one"
    _insert_job(apply_db, url)
    form = {"field_count": 2, "fields": [{"label": "Email", "value": "a@b.c"}]}
    apply_db.execute(
        "UPDATE jobs SET apply_form_filled = ? WHERE url = ?",
        (json.dumps(form), url),
    )
    apply_db.commit()

    launcher.mark_prepare_review(url, error="partial fill", duration_ms=1200)

    row = apply_db.execute(
        "SELECT apply_status, apply_error, apply_duration_ms, apply_form_filled FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row["apply_status"] == "prepare_review"
    assert row["apply_error"] == "partial fill"
    assert row["apply_duration_ms"] == 1200
    assert json.loads(row["apply_form_filled"])["field_count"] == 2


def test_acquire_job_staged_only_picks_staged(apply_db):
    from applypilot.apply import launcher

    _insert_job(apply_db, "https://jobs.example.com/ready")
    _insert_job(apply_db, "https://jobs.example.com/staged", status="staged")
    _insert_job(apply_db, "https://jobs.example.com/review", status="prepare_review")

    ready = launcher.acquire_job(min_score=0, worker_id=0, queue_mode="default")
    assert ready is not None
    assert ready["url"] == "https://jobs.example.com/ready"
    assert launcher.acquire_job(min_score=0, worker_id=1, queue_mode="default") is None

    staged = launcher.acquire_job(min_score=0, worker_id=2, queue_mode="staged_only")
    assert staged is not None
    assert staged["url"] == "https://jobs.example.com/staged"

    assert launcher.acquire_job(min_score=0, worker_id=3, queue_mode="staged_only") is None


def test_default_acquire_skips_prepare_review_and_staged(apply_db):
    from applypilot.apply import launcher

    _insert_job(apply_db, "https://jobs.example.com/review", status="prepare_review")
    _insert_job(apply_db, "https://jobs.example.com/staged", status="staged")

    assert launcher.acquire_job(min_score=0, worker_id=0, queue_mode="default") is None


def test_stage_unstage_dismiss_applications(apply_db):
    from applypilot.server import applications as apps

    url = "https://jobs.example.com/review"
    _insert_job(apply_db, url, status="prepare_review")

    assert apps.stage_application(url) is True
    row = apply_db.execute("SELECT apply_status FROM jobs WHERE url = ?", (url,)).fetchone()
    assert row["apply_status"] == "staged"

    assert apps.unstage_application(url) is True
    row = apply_db.execute("SELECT apply_status FROM jobs WHERE url = ?", (url,)).fetchone()
    assert row["apply_status"] == "prepare_review"

    assert apps.dismiss_application(url) is True
    row = apply_db.execute(
        "SELECT apply_status, apply_form_filled FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row["apply_status"] is None


def test_bulk_stage_applications(apply_db):
    from applypilot.server import applications as apps

    urls = [
        "https://jobs.example.com/a",
        "https://jobs.example.com/b",
        "https://jobs.example.com/c",
    ]
    for u in urls[:2]:
        _insert_job(apply_db, u, status="prepare_review")
    _insert_job(apply_db, urls[2], status="failed")

    result = apps.bulk_stage_applications(urls, "stage")
    assert result["updated"] == 2
    assert urls[2] in result["skipped"]

    staged = apply_db.execute(
        "SELECT url FROM jobs WHERE apply_status = 'staged' ORDER BY url"
    ).fetchall()
    assert [r["url"] for r in staged] == urls[:2]


def test_field_override_affects_resolver_on_second_fill(tmp_path, monkeypatch):
    from applypilot import config
    from applypilot import database
    from applypilot.apply.direct import resolver
    from applypilot.apply.direct.profile_binding import Field
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    database.close_connection()
    database.init_db()
    conn = database.get_connection()

    database.set_field_override("Phone", "+1 555 0100", conn=conn)
    fields = [Field(label="Phone", type="tel", tag="input", key="phone")]
    out = resolver.resolve(fields, {"phone": "+1 555 9999"}, conn=conn, gemini_enabled=False)
    assert out.answers["phone"] == "+1 555 0100"
    assert out.via["phone"] == "override:user"
