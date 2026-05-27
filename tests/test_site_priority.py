"""Tests for Naukri / Wellfound discover and apply priority."""

from applypilot.apply.eligibility import ats_priority_sql_case
from applypilot.discovery.site_priority import prioritize_site_dicts
from applypilot.discovery.smartextract import build_scrape_targets, load_sites


def test_load_sites_puts_naukri_and_wellfound_first():
    names = [s["name"] for s in load_sites()]
    assert names[:2] == ["Naukri", "Wellfound"]


def test_build_scrape_targets_prioritizes_naukri_before_other_boards():
    sites = [
        {"name": "Dice", "url": "https://dice.com?q={query_encoded}", "type": "search"},
        {"name": "Naukri", "url": "https://naukri.com?q={query_encoded}", "type": "search"},
        {"name": "Wellfound", "url": "https://wellfound.com/jobs", "type": "static"},
    ]
    search_cfg = {"queries": [{"query": "python"}], "locations": []}
    targets = build_scrape_targets(sites=sites, search_cfg=search_cfg)
    assert targets[0]["name"] == "Naukri"
    assert targets[1]["name"] == "Wellfound"


def test_prioritize_site_dicts_is_stable_within_tier():
    sites = [
        {"name": "Zebra"},
        {"name": "Naukri"},
        {"name": "Alpha"},
        {"name": "Wellfound"},
    ]
    ordered = prioritize_site_dicts(sites)
    assert [s["name"] for s in ordered[:2]] == ["Naukri", "Wellfound"]


def test_ats_priority_sql_case_prefers_naukri_and_wellfound():
    sql = ats_priority_sql_case()
    naukri_pos = sql.index("naukri.com")
    wellfound_pos = sql.index("wellfound.com")
    greenhouse_pos = sql.index("greenhouse")
    assert naukri_pos < wellfound_pos < greenhouse_pos
