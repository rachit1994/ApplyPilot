"""Tests for apply experience eligibility."""

from applypilot.apply.experience import (
    description_satisfies_experience_floor,
    is_too_junior_role,
)


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


def test_minimum_five_years_satisfies_experience_floor():
    assert description_satisfies_experience_floor(
        "Software Engineer",
        "Minimum 5 years of experience in Python.",
    )


def test_minimum_five_years_role_is_not_too_junior_without_senior_title():
    assert not is_too_junior_role(
        "Backend Engineer",
        "Minimum 5 years of experience required. You may mentor junior engineers.",
    )


def test_unspecified_experience_is_not_too_junior():
    assert not is_too_junior_role("Staff Engineer", "Build scalable APIs.")
