"""Tests for apply experience eligibility."""

from applypilot.apply.experience import is_too_junior_role


def test_intern_role_is_too_junior():
    assert is_too_junior_role("Software Engineering Intern", "Summer internship for students")


def test_entry_level_years_is_too_junior():
    assert is_too_junior_role(
        "Backend Engineer",
        "Requirements: 2-4 years of experience in Python.",
    )


def test_senior_five_plus_is_not_too_junior():
    assert not is_too_junior_role(
        "Senior Engineer",
        "5+ years building distributed systems.",
    )


def test_unspecified_experience_is_not_too_junior():
    assert not is_too_junior_role("Staff Engineer", "Build scalable APIs.")
