"""Pure-logic tests for the LinkedIn India harvester (no live browser)."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.discovery import linkedin_harvest as h


def test_search_url_is_india_scoped():
    url = h.build_search_url("backend engineer")
    assert "geoId=102713980" in url
    assert "location=India" in url
    assert "keywords=backend+engineer" in url


def test_page_url_with_start_replaces_existing_offset():
    url = h.build_search_url("backend engineer")
    assert "start=0" in url
    next_url = h.page_url_with_start(url, 25)
    assert "start=25" in next_url
    assert "start=0" not in next_url
    assert "keywords=backend+engineer" in next_url


def test_linkedin_job_id_from_url():
    assert h.linkedin_job_id_from_url("https://www.linkedin.com/jobs/view/123456/") == "123456"
    assert h.linkedin_job_id_from_url("https://www.linkedin.com/jobs/search/?currentJobId=987") == "987"
    assert h.linkedin_job_id_from_url("https://example.com/jobs/123") is None


def test_linkedin_block_reason_detects_login_and_security_pages():
    assert h.linkedin_block_reason("https://www.linkedin.com/login") == "linkedin_login_required"
    assert h.linkedin_block_reason("https://www.linkedin.com/checkpoint/challenge/123") == "linkedin_checkpoint"
    assert h.linkedin_block_reason("https://www.linkedin.com/jobs/search/", "Security verification") == (
        "linkedin_bot_or_security_check"
    )
    assert h.linkedin_block_reason("https://jobs.lever.co/acme/1", "captcha") is None


def test_listing_page_budget_is_bounded():
    assert h.listing_page_budget(1) == 1
    assert h.listing_page_budget(10) == 2
    assert h.listing_page_budget(100) == 5


def test_delay_ms_within_bounds():
    for _ in range(20):
        value = h.delay_ms((10, 20))
        assert 10 <= value <= 20


def test_clean_redirect_unwraps_linkedin_interstitial():
    wrapped = "https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fjobs.lever.co%2Facme%2F1"
    assert h.clean_redirect_url(wrapped) == "https://jobs.lever.co/acme/1"


def test_clean_redirect_drops_non_redirected_linkedin_url():
    # Stayed on LinkedIn (Easy Apply / login wall) -> not an external apply page.
    assert h.clean_redirect_url("https://www.linkedin.com/jobs/view/123") is None


def test_clean_redirect_keeps_external_url():
    assert h.clean_redirect_url("https://careers.acme.in/job/42") == "https://careers.acme.in/job/42"


def test_intermediate_apply_url_detection():
    assert h.is_probable_intermediate_apply_url("https://careers.acme.in/jobs/42")
    assert not h.is_probable_intermediate_apply_url("https://careers.acme.in/jobs/42/apply")
    assert not h.is_probable_intermediate_apply_url("https://boards.greenhouse.io/embed/job_app?token=1")


def test_looks_like_india():
    assert h.looks_like_india("Bengaluru, Karnataka, India")
    assert h.looks_like_india("Remote, India")
    assert h.looks_like_india("Gurugram, Haryana")
    assert not h.looks_like_india("San Francisco, CA")
    assert not h.looks_like_india("")


def test_role_relevance_detection():
    assert h.looks_role_relevant("Senior Backend Engineer - Bengaluru")
    assert h.looks_role_relevant("Full Stack Web Developer")
    assert not h.looks_role_relevant("Account Executive")


def test_same_host_or_subdomain():
    assert h.same_host_or_subdomain("https://jobs.acme.com/1", "https://jobs.acme.com/x")
    assert h.same_host_or_subdomain("https://boards.acme.com/1", "https://acme.com/jobs")
    assert h.same_host_or_subdomain("https://acme.com/jobs", "https://boards.acme.com/1")
    assert not h.same_host_or_subdomain("https://other.com/1", "https://acme.com/jobs")


def test_known_job_host_detection():
    assert h.is_known_job_host("https://jobs.lever.co/acme/1")
    assert h.is_known_job_host("https://acme.wd5.myworkdayjobs.com/jobs/job/1")
    assert not h.is_known_job_host("https://linkedin.com/jobs/view/1")


def test_company_slug_extraction():
    assert h.company_slug_from_url("https://www.linkedin.com/company/acme-india/") == "acme-india"
    assert h.company_slug_from_url("https://example.com/x") is None


def test_is_linkedin_url():
    assert h.is_linkedin_url("https://www.linkedin.com/jobs/view/1")
    assert not h.is_linkedin_url("https://jobs.lever.co/acme/1")


@pytest.fixture
def inbox_db(monkeypatch, tmp_path):
    db = Path(tmp_path) / "applypilot.db"
    monkeypatch.setattr("applypilot.config.APP_DIR", Path(tmp_path))
    monkeypatch.setattr("applypilot.config.DB_PATH", db)
    import applypilot.database as database

    monkeypatch.setattr(database, "DB_PATH", db)
    database.close_connection()
    database.init_db()
    yield db
    database.close_connection()


def test_store_harvested_jobs_dedupes_and_drops_linkedin(inbox_db):
    jobs = [
        {"url": "https://jobs.lever.co/acme/1", "title": "Backend Eng",
         "company": "Acme", "location": "Bengaluru, India"},
        # duplicate company URL -> de-dup
        {"url": "https://jobs.lever.co/acme/1", "title": "Backend Eng",
         "company": "Acme", "location": "Bengaluru, India"},
        # a LinkedIn URL must never be stored
        {"url": "https://www.linkedin.com/jobs/view/9", "title": "x",
         "company": "y", "location": "India"},
    ]
    result = h.store_harvested_jobs(jobs)
    assert result["new"] == 1

    from applypilot.database import get_connection

    rows = get_connection().execute(
        "SELECT url, application_url, full_description, site FROM jobs"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["url"] == "https://jobs.lever.co/acme/1"
    assert rows[0]["application_url"] == "https://jobs.lever.co/acme/1"
    assert "Acme" in (rows[0]["full_description"] or "")
    assert rows[0]["site"] == "LinkedIn->Company"
    assert not any("linkedin.com" in (r["url"] or "") for r in rows)


def test_store_harvested_jobs_prefers_resolved_form_url(inbox_db):
    result = h.store_harvested_jobs(
        [
            {
                "url": "https://careers.acme.in/jobs/42",
                "application_url": "https://careers.acme.in/jobs/42/apply",
                "title": "Backend Eng",
                "company": "Acme",
                "location": "Bengaluru, India",
            }
        ]
    )
    assert result["new"] == 1

    from applypilot.database import get_connection

    row = get_connection().execute(
        "SELECT url, application_url FROM jobs"
    ).fetchone()
    assert row["url"] == "https://careers.acme.in/jobs/42/apply"
    assert row["application_url"] == "https://careers.acme.in/jobs/42/apply"
