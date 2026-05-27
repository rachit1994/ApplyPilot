"""JobSpy board/country wiring from searches.yaml."""

from __future__ import annotations

from applypilot.discovery import jobspy


def test_jobspy_country_prefers_top_level_country():
    cfg = {"country": "India", "defaults": {"country_indeed": "usa"}}
    assert jobspy._jobspy_country(cfg, cfg["defaults"]) == "India"


def test_jobspy_country_falls_back_to_defaults():
    cfg = {"defaults": {"country_indeed": "uk"}}
    assert jobspy._jobspy_country(cfg, cfg["defaults"]) == "uk"


def test_jobspy_boards_respects_skip_boards():
    cfg = {
        "boards": ["indeed", "linkedin", "glassdoor"],
        "skip_boards": ["glassdoor"],
    }
    assert jobspy._jobspy_boards(cfg, None) == ["indeed", "linkedin"]


def test_glassdoor_location_uses_india_defaults():
    loc = jobspy._glassdoor_location("Bengaluru, Karnataka", {})
    assert loc == "Bangalore"
