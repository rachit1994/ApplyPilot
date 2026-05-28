"""Tests for LinkedIn / Wellfound discover and apply priority."""

from applypilot.apply.eligibility import ats_priority_sql_case, priority_boards_only_where_clause
from applypilot.discovery.site_priority import filter_priority_site_dicts, job_is_priority_board, prioritize_site_dicts
from applypilot.discovery.smartextract import build_scrape_targets, load_sites


def test_load_sites_puts_linkedin_and_wellfound_first():
    names = [s["name"] for s in load_sites()]
    assert names[:2] == ["LinkedIn", "Wellfound"]


def test_build_scrape_targets_prioritizes_linkedin_before_other_boards():
    sites = [
        {"name": "Dice", "url": "https://dice.com?q={query_encoded}", "type": "search"},
        {"name": "LinkedIn", "url": "https://linkedin.com?q={query_encoded}", "type": "search"},
        {"name": "Wellfound", "url": "https://wellfound.com/jobs", "type": "static"},
    ]
    search_cfg = {"queries": [{"query": "python"}], "locations": []}
    targets = build_scrape_targets(sites=sites, search_cfg=search_cfg)
    assert targets[0]["name"] == "LinkedIn"
    assert targets[1]["name"] == "Wellfound"


def test_prioritize_site_dicts_is_stable_within_tier():
    sites = [
        {"name": "Zebra"},
        {"name": "LinkedIn"},
        {"name": "Alpha"},
        {"name": "Wellfound"},
    ]
    ordered = prioritize_site_dicts(sites)
    assert [s["name"] for s in ordered[:2]] == ["LinkedIn", "Wellfound"]


def test_priority_boards_only_where_clause_matches_linkedin_and_wellfound():
    sql = priority_boards_only_where_clause()
    assert "linkedin.com" in sql
    assert "wellfound.com" in sql
    assert "greenhouse" not in sql


def test_job_is_priority_board():
    assert job_is_priority_board({"site": "LinkedIn", "url": "https://www.linkedin.com/jobs/view/1"})
    assert job_is_priority_board({"site": "Wellfound", "url": "https://wellfound.com/jobs/1"})
    assert not job_is_priority_board({"site": "greenhouse:acme", "url": "https://boards.greenhouse.io/x"})


def test_filter_priority_site_dicts():
    sites = [{"name": "Dice"}, {"name": "LinkedIn"}, {"name": "Wellfound"}]
    assert [s["name"] for s in filter_priority_site_dicts(sites)] == ["LinkedIn", "Wellfound"]


def test_ats_priority_sql_case_prefers_linkedin_and_wellfound():
    sql = ats_priority_sql_case()
    linkedin_pos = sql.index("linkedin.com")
    wellfound_pos = sql.index("wellfound.com")
    greenhouse_pos = sql.index("greenhouse")
    assert linkedin_pos < wellfound_pos < greenhouse_pos
