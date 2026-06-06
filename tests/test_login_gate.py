"""Tests for the login pause/resume gate, login-wall detection, generic adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.apply import login_gate
from applypilot.apply.direct import login_detect


@pytest.fixture
def gate_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("applypilot.config.APP_DIR", Path(tmp_path))
    login_gate.clear()
    yield tmp_path
    login_gate.clear()


# --- login gate -----------------------------------------------------------

def test_gate_request_pending_resume(gate_dir):
    assert login_gate.is_paused() is False
    login_gate.request_login("naukri.com", url="https://naukri.com/login")
    assert login_gate.is_paused() is True
    assert login_gate.is_domain_pending("naukri.com")
    doms = [p["domain"] for p in login_gate.pending()]
    assert "naukri.com" in doms

    login_gate.resume("naukri.com")
    assert login_gate.is_paused() is False
    assert not login_gate.is_domain_pending("naukri.com")


def test_gate_records_no_google_login_reason(gate_dir):
    login_gate.request_login(
        "cutshort.io",
        url="https://cutshort.io/login",
        reason="login_required_no_google",
        has_google_signin=False,
    )
    [pending] = login_gate.pending()
    assert pending["domain"] == "cutshort.io"
    assert pending["reason"] == "login_required_no_google"
    assert pending["has_google_signin"] is False


def test_gate_resume_all(gate_dir):
    login_gate.request_login("naukri.com")
    login_gate.request_login("wellfound.com")
    assert login_gate.is_paused()
    login_gate.resume()  # all
    assert login_gate.pending() == []
    assert login_gate.is_paused() is False


def test_gate_wait_for_resume_returns_immediately_when_not_pending(gate_dir):
    assert login_gate.wait_for_resume("nobody.com", timeout_s=0.1, poll_s=0.05) is True


# --- login-wall detection -------------------------------------------------

def test_detect_password_field_with_no_form_is_login():
    assert login_detect.detect_login_required(
        "https://www.naukri.com/nlogin/login",
        body_text="Login to your account",
        has_password_field=True,
        application_field_count=2,
    )


def test_detect_explicit_phrase_is_login():
    assert login_detect.detect_login_required(
        "https://careers.acme.in/job/1",
        body_text="Please sign in to apply for this role.",
        has_password_field=False,
        application_field_count=5,
    )


def test_apply_form_with_many_fields_is_not_login():
    # A real application form (lots of fields) must not be treated as a login wall
    # even if it has a password field (some forms set an account password).
    assert not login_detect.detect_login_required(
        "https://careers.acme.in/apply/42",
        body_text="Apply for Backend Engineer. Upload your resume.",
        has_password_field=True,
        application_field_count=9,
    )


def test_detect_google_signin_available():
    assert login_detect.has_google_signin("Continue with Google")
    assert login_detect.has_google_signin(html="<a href='https://accounts.google.com/o/oauth2'>")
    assert not login_detect.has_google_signin("Sign in with email and password")


def test_login_domain():
    assert login_detect.login_domain("https://www.naukri.com/x") == "naukri.com"
    assert login_detect.login_domain("https://jobs.lever.co/acme/1") == "jobs.lever.co"


# --- generic adapter ------------------------------------------------------

def test_generic_adapter_enabled_by_default(monkeypatch):
    from applypilot.apply.direct import generic

    monkeypatch.delenv("APPLYPILOT_DIRECT_GENERIC", raising=False)
    assert generic.generic_form_enabled() is True
    monkeypatch.setenv("APPLYPILOT_DIRECT_GENERIC", "0")
    assert generic.generic_form_enabled() is False
    assert generic.ADAPTER.family == "generic"


# --- launcher resume/requeue ---------------------------------------------

@pytest.fixture
def apply_db(monkeypatch, tmp_path):
    from applypilot import config, database

    db = Path(tmp_path) / "applypilot.db"
    monkeypatch.setattr(config, "APP_DIR", Path(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.close_connection()
    database.init_db()
    login_gate.clear()
    yield db
    database.close_connection()
    login_gate.clear()


def test_resume_login_requeues_awaiting_jobs(apply_db):
    from applypilot.apply import launcher
    from applypilot.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (url, title, site, apply_status, apply_error) "
        "VALUES ('https://careers.acme.in/1', 'Eng', 'LinkedIn->Company', "
        "'awaiting_login', 'awaiting_login:acme.in')"
    )
    conn.commit()

    login_gate.request_login("acme.in", url="https://careers.acme.in/1")
    result = launcher.resume_login("acme.in")
    assert result["requeued"] == 1
    assert login_gate.is_domain_pending("acme.in") is False

    status = get_connection().execute(
        "SELECT apply_status FROM jobs WHERE url = 'https://careers.acme.in/1'"
    ).fetchone()[0]
    assert status is None  # back in the queue


def test_resume_login_requeues_no_google_login_jobs(apply_db):
    from applypilot.apply import launcher
    from applypilot.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (url, title, site, apply_status, apply_error) "
        "VALUES ('https://careers.cutshort.io/1', 'Eng', 'LinkedIn->Company', "
        "'awaiting_login', 'awaiting_login:cutshort.io;login_required_no_google')"
    )
    conn.commit()

    login_gate.request_login(
        "cutshort.io",
        url="https://careers.cutshort.io/1",
        reason="login_required_no_google",
        has_google_signin=False,
    )
    result = launcher.resume_login("cutshort.io")
    assert result["requeued"] == 1
    assert login_gate.is_domain_pending("cutshort.io") is False

    status = get_connection().execute(
        "SELECT apply_status FROM jobs WHERE url = 'https://careers.cutshort.io/1'"
    ).fetchone()[0]
    assert status is None
