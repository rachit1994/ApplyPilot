"""Tests for template filling, keyword density, and A-grade routing."""

from __future__ import annotations

import pytest

from applypilot.scoring.keyword_extractor import extract_top_keywords, keyword_overlap_ratio
from applypilot.scoring.templates import (
    fill_template,
    is_a_grade_job,
    keyword_density_ok,
    load_keyword_pools,
    tailor_via_template,
)


def test_extract_top_keywords_filters_stopwords_and_short_tokens() -> None:
    words = extract_top_keywords(
        "The AI and ML team builds React apps with Node.js for the web.",
        top_n=10,
    )
    lowered = [w.lower() for w in words]
    assert "the" not in lowered
    assert "react" in lowered
    assert "node" in lowered


def test_keyword_overlap_ratio_partial_match() -> None:
    job = "Senior React TypeScript engineer with GraphQL and Kubernetes experience."
    resume = "Built React dashboards and TypeScript APIs."
    ratio = keyword_overlap_ratio(resume, job, top_n=5)
    assert 0.0 < ratio < 1.0


def test_fill_template_placeholders() -> None:
    template = (
        "Dear {company},\n"
        "Applying for {role_title}.\n"
        "Focus: {keyword_1}, {keyword_2}.\n"
    )
    job = {
        "site": "Acme Corp",
        "title": "Senior React Engineer",
        "full_description": "We use React and TypeScript daily.",
    }
    pools = load_keyword_pools()
    filled = fill_template(template, job, pools, "A1_senior_fe")
    assert "Acme Corp" in filled
    assert "Senior React Engineer" in filled
    assert "React" in filled
    assert "{company}" not in filled
    assert "{keyword_1}" not in filled


def test_fill_template_empty_keywords_when_no_pool_match() -> None:
    template = "Keywords: {keyword_1} / {keyword_2}"
    job = {
        "site": "Co",
        "title": "Role",
        "full_description": "No overlap with pool.",
    }
    filled = fill_template(template, job, {"A3_full_stack": ["blockchain"]}, "A3_full_stack")
    assert filled == "Keywords:  / "


def test_keyword_density_ok_passes_when_overlap_high() -> None:
    job_desc = "React TypeScript Node PostgreSQL AWS microservices REST GraphQL"
    resume = "React TypeScript Node PostgreSQL AWS experience shipping production systems."
    assert keyword_density_ok(resume, job_desc, threshold=0.4)


def test_keyword_density_ok_fails_when_overlap_low() -> None:
    job_desc = "Rust embedded firmware bare-metal automotive CAN bus"
    resume = "React TypeScript frontend dashboards and design systems."
    assert not keyword_density_ok(resume, job_desc, threshold=0.4)


@pytest.mark.parametrize(
    ("job", "profile", "expected"),
    [
        ({"fit_score": 10, "site": "RandomCo"}, {}, True),
        ({"fit_score": 7, "site": "Stripe"}, {"tailor": {"a_grade": {"target_companies": ["Stripe"]}}}, True),
        ({"fit_score": 7, "site": "stripe"}, {"tailor": {"a_grade": {"target_companies": ["Stripe"]}}}, True),
        ({"fit_score": 8, "site": "Other"}, {}, False),
        (
            {"fit_score": 8, "site": "Other"},
            {"tailor": {"a_grade": {"min_score": 9, "target_companies": []}}},
            False,
        ),
    ],
)
def test_is_a_grade_job(job: dict, profile: dict, expected: bool) -> None:
    assert is_a_grade_job(job, profile) is expected


def test_tailor_via_template_returns_none_without_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("applypilot.scoring.templates.TEMPLATES_DIR", tmp_path)
    assert tailor_via_template({"title": "Software Engineer"}, {}) is None


def test_tailor_via_template_fills_resume(tmp_path, monkeypatch) -> None:
    templates = tmp_path
    resumes = templates / "resumes"
    resumes.mkdir(parents=True)
    (resumes / "A3_full_stack.txt").write_text(
        "Resume for {company} — {role_title}\nSkills: {keyword_1}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("applypilot.scoring.templates.TEMPLATES_DIR", templates)

    result = tailor_via_template(
        {
            "title": "Full Stack Developer",
            "site": "TestCo",
            "full_description": "TypeScript and React required.",
        },
        {},
    )
    assert result is not None
    text, report = result
    assert "TestCo" in text
    assert report["source"] == "template"
    assert report["archetype"] == "A3_full_stack"
    assert report["status"] == "approved"
