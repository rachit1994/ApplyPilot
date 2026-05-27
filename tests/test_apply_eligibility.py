"""Tests for pre-acquire apply eligibility classification."""

from applypilot.apply.eligibility import (
    ApplyDecision,
    classify_apply_target,
    is_ats_url,
    load_exclude_title_substrings,
)


def test_linkedin_url_is_manual_even_when_salary_ok():
    job = {
        "url": "https://www.linkedin.com/jobs/view/999",
        "application_url": "https://www.linkedin.com/jobs/view/999",
        "title": "Senior Engineer",
        "site": "linkedin",
        "salary": "₹55L",
        "location": "Bangalore, India",
        "full_description": "5+ years experience required.",
    }
    result = classify_apply_target(job)
    assert result.decision == ApplyDecision.MANUAL
    assert result.reason == "manual ATS"


def test_greenhouse_url_is_eligible():
    job = {
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "application_url": "https://boards.greenhouse.io/acme/jobs/1",
        "title": "Staff Engineer",
        "site": "greenhouse",
        "salary": "₹60L",
        "location": "Bangalore, India",
    }
    result = classify_apply_target(job)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_hourly_gig_title_eligible_in_queue_mode():
    job = {
        "url": "https://example.com/job",
        "application_url": "https://boards.greenhouse.io/acme/jobs/2",
        "title": "Remote Javascript Developer | $65/hr",
        "site": "indeed",
        "salary": "$120k",
        "location": "Remote",
    }
    result = classify_apply_target(job)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_hourly_gig_strict_mode_skips():
    job = {
        "url": "https://example.com/job",
        "application_url": "https://boards.greenhouse.io/acme/jobs/2",
        "title": "Remote Javascript Developer | $65/hr",
        "site": "indeed",
        "salary": "$120k",
        "location": "Remote",
    }
    result = classify_apply_target(job, strict=True)
    assert result.decision == ApplyDecision.SKIP_PERMANENT


def test_missing_apply_url_uses_job_url():
    job = {
        "url": "https://boards.greenhouse.io/acme/jobs/3",
        "application_url": None,
        "title": "Backend Engineer",
        "site": "indeed",
        "salary": "₹55L",
        "location": "Bangalore",
        "full_description": "Senior backend role.",
    }
    result = classify_apply_target(job)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_low_salary_eligible_in_queue_mode():
    job = {
        "url": "https://boards.greenhouse.io/acme/jobs/4",
        "application_url": "https://boards.greenhouse.io/acme/jobs/4",
        "title": "Engineer",
        "site": "greenhouse",
        "salary": "₹35L",
        "location": "Bangalore, India",
    }
    result = classify_apply_target(job)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_low_salary_strict_mode_skips():
    job = {
        "url": "https://boards.greenhouse.io/acme/jobs/4",
        "application_url": "https://boards.greenhouse.io/acme/jobs/4",
        "title": "Engineer",
        "site": "greenhouse",
        "salary": "₹35L",
        "location": "Bangalore, India",
    }
    result = classify_apply_target(job, strict=True)
    assert result.decision == ApplyDecision.SKIP_PERMANENT
    assert result.reason == "not_eligible_salary"


def test_junior_experience_strict_mode_skips():
    job = {
        "url": "https://boards.greenhouse.io/acme/jobs/5",
        "application_url": "https://boards.greenhouse.io/acme/jobs/5",
        "title": "Engineer",
        "site": "greenhouse",
        "salary": "₹55L",
        "location": "Bangalore",
        "full_description": "2-3 years of experience required.",
    }
    result = classify_apply_target(job, strict=True)
    assert result.decision == ApplyDecision.SKIP_PERMANENT
    assert result.reason == "not_eligible_experience"


def test_ats_only_rejects_non_ats():
    job = {
        "url": "https://careers.example.com/role",
        "application_url": "https://careers.example.com/role",
        "title": "Engineer",
        "site": "company",
        "salary": "₹50L",
        "location": "Bangalore",
    }
    result = classify_apply_target(job, ats_only=True)
    assert result.decision == ApplyDecision.MANUAL
    assert result.reason == "non_ats_url"


def test_ats_only_accepts_greenhouse_sourced_company_apply_url():
    job = {
        "url": "https://stripe.com/jobs/listing/software-engineer/123",
        "application_url": "https://stripe.com/jobs/listing/software-engineer/123/apply",
        "title": "Software Engineer",
        "site": "Greenhouse:Stripe",
        "salary": "$180k",
        "location": "Remote",
    }
    result = classify_apply_target(job, ats_only=True)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_is_ats_url_markers():
    assert is_ats_url("https://jobs.lever.co/acme/abc")
    assert not is_ats_url("https://www.linkedin.com/jobs/view/1")


def test_load_exclude_title_substrings_is_list():
    subs = load_exclude_title_substrings()
    assert isinstance(subs, list)
