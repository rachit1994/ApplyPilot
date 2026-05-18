"""Tests for referral resume helpers."""

from applypilot.outreach.referral_resume import company_from_job, _prefix_for_job


def test_company_from_job_site():
    job = {"title": "Engineer", "site": "Acme Corp (via LinkedIn)"}
    assert company_from_job(job) == "Acme Corp"


def test_company_from_job_title_at():
    job = {"title": "Staff Engineer at Stripe", "site": "linkedin"}
    assert company_from_job(job) == "Stripe"


def test_prefix_for_job_sanitizes():
    job = {"title": "Sr. SWE / Platform!", "site": "Foo & Bar"}
    prefix = _prefix_for_job(job)
    assert "/" not in prefix
    assert "&" not in prefix
