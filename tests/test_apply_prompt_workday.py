from __future__ import annotations

from applypilot.apply.prompt import (
    _build_ats_form_repair_section,
    _build_form_verify_section,
    _extract_experience_ranges,
)


RESUME = """
EXPERIENCE

Full Stack Engineer — AI Platform | 2026 – Present
Happening Today · Bengaluru

Full Stack Engineer — AI Products | 2024 – 2025
MIRA · Remote

Tech Lead / Senior Full Stack Engineer | 2022 – 2024
Delta Exchange · Bengaluru
"""


def test_extract_experience_ranges_uses_safe_month_defaults():
    rows = _extract_experience_ranges(RESUME)

    assert rows[0] == {
        "title": "Full Stack Engineer — AI Platform",
        "company": "Happening Today",
        "start_month": "01",
        "start_year": "2026",
        "end_month": "",
        "end_year": "",
        "current": "yes",
    }
    assert rows[1]["company"] == "MIRA"
    assert rows[1]["start_month"] == "01"
    assert rows[1]["end_month"] == "12"
    assert rows[1]["end_year"] == "2025"


def test_ats_repair_section_tells_agent_to_fix_invalid_dates_generally():
    section = _build_ats_form_repair_section(RESUME)

    assert "ATS FORM REPAIR" in section
    assert "Invalid Date" in section
    assert "Never leave a Month field as \"MM\"" in section
    assert "On any multi-step ATS form" in section
    assert "missing/sparse" in section
    assert "bodyText" in section
    assert "Happening Today / Full Stack Engineer" in section
    assert "from=01/2026" in section
    assert "to=12/2025" in section


def test_verify_page_state_reports_date_widgets():
    section = _build_form_verify_section()

    assert "dateWidgets" in section
    assert "invalidFields" in section
    assert "disabledButtons" in section
    assert "bodyText" in section
    assert "[aria-label*=\"Month\"]" in section
    assert "[aria-label*=\"Year\"]" in section
