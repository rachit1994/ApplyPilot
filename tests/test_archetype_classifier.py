"""Tests for deterministic job-title archetype classification."""

from __future__ import annotations

import pytest

from applypilot.scoring.templates import DEFAULT_ARCHETYPE, classify_archetype

# (title, expected_archetype)
_TITLE_CASES: list[tuple[str, str]] = [
    ("Engineering Manager", "A8_eng_manager"),
    ("Eng Manager, Platform", "A8_eng_manager"),
    ("EM Manager", "A8_eng_manager"),
    ("Founding Engineer", "A6_founding"),
    ("Founder's Engineer", "A6_founding"),
    ("Solutions Engineer", "A7_solutions"),
    ("Solution Engineer", "A7_solutions"),
    ("Forward Deployed Engineer", "A7_solutions"),
    ("Customer Engineer", "A7_solutions"),
    ("Partner Engineer", "A7_solutions"),
    ("AI Engineer", "A4_ai_ml"),
    ("ML Engineer", "A4_ai_ml"),
    ("Machine Learning Engineer", "A4_ai_ml"),
    ("Applied AI Engineer", "A4_ai_ml"),
    ("LLM Engineer", "A4_ai_ml"),
    ("Gen AI Engineer", "A4_ai_ml"),
    ("MLOps Engineer", "A4_ai_ml"),
    ("Staff Engineer", "A5_staff"),
    ("Principal Engineer", "A5_staff"),
    ("Distinguished Engineer", "A5_staff"),
    ("Software Architect", "A5_staff"),
    ("Frontend Tech Lead", "A2_frontend_lead"),
    ("Front-end Lead", "A2_frontend_lead"),
    ("UI Tech Lead", "A2_frontend_lead"),
    ("Lead Frontend Engineer", "A2_frontend_lead"),
    ("Senior Frontend Engineer", "A1_senior_fe"),
    ("Frontend Engineer", "A1_senior_fe"),
    ("React Developer", "A1_senior_fe"),
    ("UI Engineer", "A1_senior_fe"),
    ("Senior Full Stack Engineer", "A3_full_stack"),
    ("Full Stack Developer", "A3_full_stack"),
    ("TypeScript Developer", "A3_full_stack"),
    ("Node.js Developer", "A3_full_stack"),
    ("Software Engineer", DEFAULT_ARCHETYPE),
    ("Backend Engineer", DEFAULT_ARCHETYPE),
    ("Senior Lead Frontend Engineer", "A2_frontend_lead"),
    ("Research Engineer", DEFAULT_ARCHETYPE),
]


@pytest.mark.parametrize(("title", "expected"), _TITLE_CASES)
def test_classify_archetype_title(title: str, expected: str) -> None:
    assert classify_archetype(title) == expected


def test_classify_uses_description_snippet() -> None:
    assert (
        classify_archetype("Software Engineer", "We need a founding engineer mindset.")
        == "A6_founding"
    )


def test_classify_manager_before_ai_in_title() -> None:
    """More-specific rules win — EM title should not classify as AI from description alone."""
    assert classify_archetype("Engineering Manager", "machine learning team") == "A8_eng_manager"
