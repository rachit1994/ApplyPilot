"""Tests for pre-score filter before Gemini scoring."""

from __future__ import annotations

import os

import pytest

from applypilot.discovery import _filters
from applypilot.scoring.pre_filter import (
    pre_filter_disabled,
    pre_score_filter,
    resolve_filter_checks,
)


@pytest.fixture(autouse=True)
def _clear_filter_cache():
    _filters.clear_filter_cache()
    yield
    _filters.clear_filter_cache()


PROFILE = {"compensation": {"salary_currency": "INR"}}


def test_pre_filter_rejects_intern_title():
    verdict = pre_score_filter(
        {
            "title": "Software Engineering Intern",
            "full_description": "Build features.",
            "location": "Remote",
        },
        PROFILE,
        {"exclude_titles": [], "include_titles": []},
    )
    assert not verdict.passes
    assert verdict.reason == "title:junior_or_intern"


def test_pre_filter_rejects_sales_engineer():
    verdict = pre_score_filter(
        {
            "title": "Senior Sales Engineer",
            "full_description": "Quota carrying role.",
            "location": "Remote",
        },
        PROFILE,
        {},
    )
    assert not verdict.passes
    assert verdict.reason == "title:adjacent_role"


def test_pre_filter_allowlist_blocks_generic_engineer():
    verdict = pre_score_filter(
        {
            "title": "Software Engineer",
            "full_description": "Generalist role.",
            "location": "Remote",
        },
        PROFILE,
        {"include_titles": ["react", "frontend"]},
    )
    assert not verdict.passes
    assert verdict.reason == "title:not_in_allowlist"


def test_pre_filter_passes_strong_match():
    search_cfg = {
        "include_titles": [],
        "location": {"accept_patterns": ["india", "bengaluru"], "reject_patterns": []},
    }
    verdict = pre_score_filter(
        {
            "title": "Senior Frontend Engineer",
            "full_description": "React, TypeScript, Node.",
            "location": "Remote, India",
            "salary": "",
        },
        PROFILE,
        search_cfg,
    )
    assert verdict.passes
    assert verdict.reason is None
    assert verdict.pre_score >= 7


def test_pre_filter_env_disable(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DISABLE_PRE_FILTER", "1")
    assert pre_filter_disabled()
    verdict = pre_score_filter(
        {"title": "Software Engineering Intern", "full_description": "x"},
        PROFILE,
        {},
    )
    assert verdict.passes


def test_pre_filter_rejects_blocked_jd_keyword():
    verdict = pre_score_filter(
        {
            "title": "Senior Platform Engineer",
            "full_description": "This role requires active security clearance.",
            "location": "Remote",
        },
        PROFILE,
        {"blocked_keywords": ["security clearance"]},
    )
    assert not verdict.passes
    assert verdict.reason == "description:blocked_keyword"
    assert verdict.pre_score == 1


def test_filter_check_disable_allows_adjacent_title():
    verdict = pre_score_filter(
        {
            "title": "Senior Sales Engineer",
            "full_description": "Quota carrying role with Python APIs.",
            "location": "Remote",
        },
        {
            **PROFILE,
            "experience": {"target_roles": ["Senior Sales Engineer"]},
            "skills_boundary": {"languages": ["Python"]},
        },
        {
            "filter": {
                "checks": {"title_adjacent_role": False, "profile_keyword_overlap": False},
            },
        },
    )
    assert verdict.passes


def test_filter_disable_list_uses_reason_alias():
    checks = resolve_filter_checks(
        {"filter": {"disable": ["title:junior_or_intern"]}},
        {},
    )
    assert checks["title_junior_or_intern"] is False
    assert checks["title_adjacent_role"] is True


def test_profile_fit_filters_override_search_config():
    checks = resolve_filter_checks(
        {"filter": {"checks": {"blocked_keywords": True}}},
        {"fit_filters": {"checks": {"blocked_keywords": False}}},
    )
    assert checks["blocked_keywords"] is False


def test_filter_enabled_false_disables_all_checks():
    assert pre_filter_disabled({"filter": {"enabled": False}}, PROFILE)
    verdict = pre_score_filter(
        {"title": "Software Engineering Intern", "full_description": "x"},
        PROFILE,
        {"filter": {"enabled": False}},
    )
    assert verdict.passes


def test_pre_filter_allows_minimum_five_years_with_junior_mentoring_mention():
    search_cfg = {
        "include_titles": [],
        "location": {"accept_patterns": ["india", "remote"], "reject_patterns": []},
    }
    verdict = pre_score_filter(
        {
            "title": "Backend Engineer",
            "full_description": (
                "Minimum 5 years of experience in Python. "
                "You will mentor junior engineers on the team."
            ),
            "location": "Remote, India",
        },
        PROFILE,
        search_cfg,
    )
    assert verdict.passes
    assert verdict.reason is None


def test_pre_filter_allows_not_entry_level_with_five_plus_years():
    search_cfg = {
        "include_titles": [],
        "location": {"accept_patterns": ["remote"], "reject_patterns": []},
    }
    verdict = pre_score_filter(
        {
            "title": "Software Engineer",
            "full_description": (
                "This is not an entry-level role. Requires 5+ years of experience."
            ),
            "location": "Remote",
        },
        PROFILE,
        search_cfg,
    )
    assert verdict.passes
    assert verdict.reason is None


def test_pre_filter_still_rejects_clearly_junior_jd_without_senior_years():
    verdict = pre_score_filter(
        {
            "title": "Software Engineer",
            "full_description": "0-3 years of experience required. Campus hiring.",
            "location": "Remote",
        },
        PROFILE,
        {"include_titles": []},
    )
    assert not verdict.passes
    assert verdict.reason == "description:junior_signal"
