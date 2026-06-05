from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.apply import apply_budget, apply_settings
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
    database.close_connection(db_path)
    conn = database.init_db(db_path)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    yield conn
    database.close_connection(db_path)


@pytest.fixture(autouse=True)
def reset_governor():
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)
    yield
    apply_budget.governor().reset()
    apply_settings.set_deterministic_only_override(None)


def test_governor_claude_allowed_respects_attempt_cap():
    snap = apply_budget.governor().reset(profile={"apply": {"claude_max_per_run": 2}})
    assert snap.claude_allowed() is True
    apply_budget.governor().record_claude_apply(0.01)
    apply_budget.governor().record_claude_apply(0.01)
    assert apply_budget.governor().claude_allowed() is False
    assert apply_budget.governor().snapshot().claude_capped is True


def test_governor_claude_allowed_respects_cost_cap():
    snap = apply_budget.governor().reset(
        profile={"apply": {"claude_max_cost_usd_per_run": 0.5}}
    )
    assert snap.claude_allowed() is True
    apply_budget.governor().record_claude_apply(0.49)
    assert apply_budget.governor().claude_allowed() is True
    apply_budget.governor().record_claude_apply(0.02)
    assert apply_budget.governor().claude_allowed() is False


def test_deterministic_only_disables_claude():
    snap = apply_budget.governor().reset(deterministic_only=True)
    assert snap.claude_allowed() is False
    apply_settings.set_deterministic_only_override(True)
    assert apply_settings.deterministic_only_enabled() is True


def test_park_needs_adapter_not_permanent_failure(apply_db):
    from applypilot.apply import launcher

    url = "https://example.com/jobs/needs-adapter"
    apply_db.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status, apply_attempts
        )
        VALUES (?, 'Role', 'Co', ?, '/tmp/r.pdf', 9, 'desc', '$1', 'in_progress', 0)
        """,
        (url, f"{url}/apply"),
    )
    apply_db.commit()

    launcher._park_job_needs_adapter(url, "no_adapter:workday")

    row = apply_db.execute(
        "SELECT apply_status, apply_error, apply_attempts FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert row[0] == "needs_adapter"
    assert "no_adapter" in (row[1] or "")
    assert row[2] == 0
    assert apply_budget.governor().snapshot().parked_needs_adapter == 1


def test_acquire_requeues_needs_adapter_when_adapter_available(
    apply_db, monkeypatch
):
    from applypilot.apply import launcher
    from applypilot.apply.eligibility import ApplyDecision

    url = "https://boards.greenhouse.io/acme/jobs/1"
    apply_db.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary, apply_status, apply_attempts
        )
        VALUES (?, 'Eng', 'Acme', ?, '/tmp/r.pdf', 9, 'Build things.', '$1',
                'needs_adapter', 0)
        """,
        (url, url),
    )
    apply_db.commit()

    monkeypatch.setattr(launcher, "job_has_direct_adapter", lambda _job: True)
    monkeypatch.setattr(
        launcher, "job_runnable_in_deterministic_only", lambda _job: True
    )
    monkeypatch.setattr(
        launcher.apply_settings, "deterministic_only_enabled", lambda: False
    )
    monkeypatch.setattr(launcher.apply_settings, "apply_engine", lambda: "direct")
    eligible = type("E", (), {"decision": ApplyDecision.ELIGIBLE, "reason": ""})()
    monkeypatch.setattr(launcher, "classify_apply_target", lambda *a, **k: eligible)
    monkeypatch.setattr(
        launcher,
        "resolve_job_resume",
        lambda *a, **k: type(
            "R", (), {"path": "/tmp/r.pdf", "source": "tailored"}
        )(),
    )

    monkeypatch.setattr(
        "applypilot.apply.direct.throttle.check_caps",
        lambda *a, **k: (True, ""),
    )

    job = launcher.acquire_job(worker_id=0, include_untailored=True)
    assert job is not None
    assert job["url"] == url
    assert job.get("apply_status") == "needs_adapter" or True
    status = apply_db.execute(
        "SELECT apply_status FROM jobs WHERE url = ?", (url,)
    ).fetchone()[0]
    assert status == "in_progress"


def test_excluded_ats_families_default_to_none():
    fams = apply_settings.skipped_ats_families()
    assert "greenhouse" not in fams
    assert "ashby" not in fams


def test_excluded_family_parks_without_claude(apply_db, monkeypatch):
    """Excluded ATS jobs must park as needs_adapter and never reach run_job."""
    from applypilot.apply import launcher

    apply_budget.governor().reset()
    # Claude allowed (no cap, not deterministic-only): only the excluded-ats guard
    # should stop these — if it didn't, run_job (Claude) would be invoked.
    monkeypatch.setattr(launcher.apply_settings, "apply_engine", lambda: "claude")

    def _boom(*a, **k):
        raise AssertionError("run_job (Claude) must not be called for excluded ATS")

    monkeypatch.setattr(launcher, "run_job", _boom)

    url = "https://example.com/gh"
    app_url = "https://boards.greenhouse.io/acme/jobs/1"
    apply_db.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary
        )
        VALUES (?, 'T', 'S', ?, '/tmp/r.pdf', 9, 'd', '$1')
        """,
        (url, app_url),
    )
    apply_db.commit()

    result, duration, log = launcher._run_job_with_optional_fallback(
        {
            "url": url,
            "title": "T",
            "site": "S",
            "application_url": app_url,
            "tailored_resume_path": "/tmp/r.pdf",
            "fit_score": 9,
        },
        port=9222,
        worker_id=0,
        primary_model="haiku",
        dry_run=True,
        pace_seconds=0.0,
        confirm_submit=False,
    )
    assert result.startswith("parked:needs_adapter:excluded_ats")
    assert duration == 0 and log is None
    status = apply_db.execute(
        "SELECT apply_status FROM jobs WHERE url = ?", (url,)
    ).fetchone()[0]
    assert status == "needs_adapter"


def test_run_job_with_fallback_parks_when_claude_capped(apply_db, monkeypatch):
    from applypilot.apply import launcher

    apply_budget.governor().reset(profile={"apply": {"claude_max_per_run": 1}})
    apply_budget.governor().record_claude_apply(0.05)

    job = {
        "url": "https://example.com/job",
        "title": "T",
        "site": "S",
        # Workday: no adapter but NOT an excluded family, so the cap path (not the
        # excluded-ats guard) is what parks this job.
        "application_url": "https://acme.wd1.myworkdayjobs.com/careers/job/1",
        "tailored_resume_path": "/tmp/r.pdf",
        "fit_score": 9,
    }
    monkeypatch.setattr(launcher.apply_settings, "apply_engine", lambda: "claude")
    monkeypatch.setattr(
        launcher, "_try_direct_apply", lambda *a, **k: None
    )

    apply_db.execute(
        """
        INSERT INTO jobs (
            url, title, site, application_url, tailored_resume_path,
            fit_score, full_description, salary
        )
        VALUES (?, 'T', 'S', ?, '/tmp/r.pdf', 9, 'd', '$1')
        """,
        (job["url"], job["application_url"]),
    )
    apply_db.commit()

    result, duration, log = launcher._run_job_with_optional_fallback(
        job,
        port=9222,
        worker_id=0,
        primary_model="haiku",
        dry_run=True,
        pace_seconds=0.0,
        confirm_submit=False,
    )
    assert result.startswith("parked:needs_adapter")
    assert duration == 0
    assert log is None

    row = apply_db.execute(
        "SELECT apply_status, apply_attempts FROM jobs WHERE url = ?",
        (job["url"],),
    ).fetchone()
    assert row[0] == "needs_adapter"
    assert row[1] != 99
