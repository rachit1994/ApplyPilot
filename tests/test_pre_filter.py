"""Tests for pre-score filter before Gemini scoring."""

from __future__ import annotations

import os

import pytest

from applypilot.discovery import _filters
from applypilot.scoring.pre_filter import pre_filter_disabled, pre_score_filter


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


def test_pre_filter_env_disable(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DISABLE_PRE_FILTER", "1")
    assert pre_filter_disabled()
    verdict = pre_score_filter(
        {"title": "Software Engineering Intern", "full_description": "x"},
        PROFILE,
        {},
    )
    assert verdict.passes
