"""Unit tests for LinkedIn public_id helpers."""

from applypilot.outreach.public_id import (
    is_linkedin_job_url,
    job_linkedin_url,
    public_id_from_url,
)


def test_public_id_from_profile_url() -> None:
    assert public_id_from_url("https://www.linkedin.com/in/jane-doe/") == "jane-doe"
    assert public_id_from_url("https://linkedin.com/in/Jane-Doe?trk=foo") == "jane-doe"


def test_public_id_rejects_invalid() -> None:
    assert public_id_from_url("https://www.linkedin.com/company/acme") is None
    assert public_id_from_url(None) is None


def test_is_linkedin_job_url() -> None:
    assert is_linkedin_job_url("https://www.linkedin.com/jobs/view/123")
    assert not is_linkedin_job_url("https://example.com/jobs/1")


def test_job_linkedin_url_prefers_jobs_path() -> None:
    row = {
        "url": "https://www.linkedin.com/jobs/view/123",
        "application_url": "https://boards.greenhouse.io/acme",
        "site": "LinkedIn",
    }
    assert job_linkedin_url(row) == "https://www.linkedin.com/jobs/view/123"
