"""Tests for pre-acquire apply eligibility classification."""

import sqlite3

from applypilot.apply.eligibility import (
    ApplyDecision,
    classify_apply_target,
    direct_adapter_priority_sql,
    is_ats_url,
    load_exclude_title_substrings,
)


def test_linkedin_job_page_can_flow_to_company_website_apply():
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
    assert result.decision == ApplyDecision.ELIGIBLE
    assert result.reason == "linkedin_company_website_flow"


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


def test_workatastartup_is_prioritized_as_direct_adapter_sql():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE jobs (site TEXT, url TEXT, application_url TEXT, full_description TEXT)"
    )
    conn.executemany(
        "INSERT INTO jobs VALUES (?, ?, ?, ?)",
        [
            (
                "Work at a Startup",
                f"https://www.workatastartup.com/jobs/{i}",
                f"https://www.workatastartup.com/application?signup_job_id={i}",
                "",
            )
            for i in range(10)
        ],
    )
    direct_count = conn.execute(
        f"SELECT COUNT(*) FROM jobs WHERE {direct_adapter_priority_sql()} = 0"
    ).fetchone()[0]
    assert direct_count == 10


def test_location_ineligible_ats_job_skips_before_browser():
    job = {
        "url": "https://jobs.ashbyhq.com/acme/hybrid",
        "application_url": "https://jobs.ashbyhq.com/acme/hybrid/application",
        "title": "Staff Engineer",
        "site": "Ashby:Acme",
        "salary": "$180k",
        "location": "San Francisco",
    }
    result = classify_apply_target(job, ats_only=True)
    assert result.decision == ApplyDecision.SKIP_PERMANENT
    assert result.reason == "not_eligible_location"


def test_is_ats_url_markers():
    assert is_ats_url("https://jobs.lever.co/acme/abc")
    assert not is_ats_url("https://www.linkedin.com/jobs/view/1")


def test_load_exclude_title_substrings_is_list():
    subs = load_exclude_title_substrings()
    assert isinstance(subs, list)


# --- Location / work-authorization pre-filter (India candidate) ---------------

_INDIA_PROFILE = {
    "personal": {"country": "India"},
    "work_authorization": {"require_sponsorship": "Yes"},
}
_US_PROFILE = {
    "personal": {"country": "United States"},
    "work_authorization": {"require_sponsorship": "No"},
}


def _greenhouse_job(description: str, *, location: str = "Remote") -> dict:
    return {
        "url": "https://boards.greenhouse.io/acme/jobs/42",
        "application_url": "https://boards.greenhouse.io/acme/jobs/42",
        "title": "Staff Software Engineer",
        "site": "Greenhouse:Acme",
        "salary": "$200k",
        "location": location,
        "full_description": description,
    }


def test_us_only_residency_in_description_skips_for_india_candidate():
    job = _greenhouse_job(
        "Remote role. You must live in a state where Acme, Inc. has a "
        "registered entity. We offer great benefits."
    )
    result = classify_apply_target(job, profile=_INDIA_PROFILE)
    assert result.decision == ApplyDecision.SKIP_PERMANENT
    assert result.reason == "not_eligible_location"


def test_no_sponsorship_clause_skips_when_candidate_needs_sponsorship():
    job = _greenhouse_job(
        "Great backend role. Applicants must be authorized to work in the "
        "country of employment; we are unable to sponsor work visas at this time."
    )
    result = classify_apply_target(job, profile=_INDIA_PROFILE)
    assert result.decision == ApplyDecision.SKIP_PERMANENT
    assert result.reason == "not_eligible_sponsorship"


def test_us_only_role_is_eligible_for_us_candidate():
    job = _greenhouse_job(
        "You must live in a state where Acme, Inc. has a registered entity."
    )
    result = classify_apply_target(job, profile=_US_PROFILE)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_benign_description_remains_eligible_for_india_candidate():
    job = _greenhouse_job(
        "Build distributed systems with a global, remote-first team. "
        "5+ years experience. Visa sponsorship available."
    )
    result = classify_apply_target(job, profile=_INDIA_PROFILE)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_no_sponsorship_clause_ignored_when_candidate_self_authorized():
    # Candidate in India but does NOT require sponsorship -> sponsorship clause
    # should not disqualify (only the hard US-residency clause would).
    profile = {
        "personal": {"country": "India"},
        "work_authorization": {"require_sponsorship": "No"},
    }
    job = _greenhouse_job(
        "Strong role. We do not sponsor employment visas for this position."
    )
    result = classify_apply_target(job, profile=profile)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_remote_usa_location_skips_for_india_candidate():
    job = _greenhouse_job("Great role.", location="Remote - USA")
    result = classify_apply_target(job, profile=_INDIA_PROFILE)
    assert result.decision == ApplyDecision.SKIP_PERMANENT
    assert result.reason == "not_eligible_location"


def test_north_america_remote_stays_eligible():
    # "North America, Remote" hires internationally; must NOT be blocked
    # (this was a real, confirmed application).
    job = _greenhouse_job("Great role.", location="North America, Remote")
    result = classify_apply_target(job, profile=_INDIA_PROFILE)
    assert result.decision == ApplyDecision.ELIGIBLE


def test_non_us_remote_locations_stay_eligible():
    for loc in ("Remote, Brazil", "Germany, Remote; Paris", "London, UK; Remote-Friendly"):
        job = _greenhouse_job("Great role.", location=loc)
        result = classify_apply_target(job, profile=_INDIA_PROFILE)
        assert result.decision == ApplyDecision.ELIGIBLE, loc


def test_candidate_home_city_segment_keeps_us_listing_eligible():
    # Multi-location that includes the candidate's city is fine.
    job = _greenhouse_job("Great role.", location="Remote - US; Bengaluru, India")
    result = classify_apply_target(job, profile=_INDIA_PROFILE)
    assert result.decision == ApplyDecision.ELIGIBLE
