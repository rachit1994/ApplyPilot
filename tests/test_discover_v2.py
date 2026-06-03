"""Tests for Discover v2 feeds, career targets, agent parser, and runner."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from applypilot.discovery.agent_browse import parse_jobs_json
from applypilot.discovery.career_targets import load_career_targets, partition_career_targets
from applypilot.discovery.discover_config import load_discover_config
from applypilot.discovery.feeds.remoteok import fetch_jobs as remoteok_fetch
from applypilot.discovery.funded_startups import (
    build_funded_startup_sites,
    career_sites_for_company,
    parse_yc_companies,
)
from applypilot.discovery.smartextract import partition_sites_by_mode


def test_parse_jobs_json_extracts_list():
    text = 'Done.\nJOBS_JSON: [{"url": "https://example.com/j/1", "title": "Staff Eng"}]\n'
    jobs = parse_jobs_json(text)
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://example.com/j/1"
    assert jobs[0]["title"] == "Staff Eng"


def test_parse_jobs_json_empty_on_missing_marker():
    assert parse_jobs_json("no jobs here") == []


def test_career_targets_load_at_least_100():
    targets = load_career_targets()
    assert len(targets) >= 100
    assert all(t.get("name") and t.get("careers_url") for t in targets)


@patch(
    "applypilot.discovery.career_targets.load_workday_employer_keys",
    return_value={"acme_wd"},
)
def test_partition_career_targets_workday_skip(mock_wd_keys):
    targets = [
        {
            "name": "TestCo",
            "careers_url": "https://example.com/careers",
            "mode": "smartextract",
            "ats": "workday",
            "workday_key": "acme_wd",
        },
        {
            "name": "AgentCo",
            "careers_url": "https://example.com/jobs",
            "mode": "agent",
            "ats": "custom",
        },
    ]
    skipped, agent, smart = partition_career_targets(targets)
    assert len(skipped) == 1
    assert skipped[0]["name"] == "TestCo"
    assert len(agent) == 1
    assert agent[0]["name"] == "AgentCo"
    assert len(smart) == 0


def test_partition_sites_by_mode():
    sites = [
        {"name": "A", "url": "https://a.com", "type": "static"},
        {"name": "B", "url": "https://b.com", "type": "static", "mode": "agent"},
    ]
    agent, smart = partition_sites_by_mode(sites)
    assert len(agent) == 1
    assert agent[0]["name"] == "B"
    assert len(smart) == 1
    assert smart[0]["name"] == "A"


def test_discover_config_defaults(tmp_path, monkeypatch):
    # Keep this test hermetic: user-local discover.yaml must not affect defaults.
    import applypilot.discovery.discover_config as dc

    monkeypatch.setattr(dc, "APP_DIR", tmp_path)
    cfg = load_discover_config()
    assert "sources" in cfg
    assert cfg["sources"]["jobspy"] is True
    assert cfg["sources"]["smartextract"] is False
    assert cfg["sources"]["funded_startups"] is False
    assert cfg["sources"]["ashby"] is True
    assert cfg["agent_discover"]["enabled"] is True


@patch("applypilot.discovery.feeds.remoteok.get_json")
def test_remoteok_fetch_parses_api(mock_get_json):
    mock_get_json.return_value = [
        {"id": "ok"},
        {
            "url": "https://remoteok.com/remote-jobs/1",
            "position": "Senior Python Dev",
            "description": "<p>Build things</p>",
            "location": "Remote",
        },
    ]
    jobs = remoteok_fetch(tags="python")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Senior Python Dev"
    assert "Build things" in (jobs[0]["description"] or "")


def test_parse_score_response_recommendation():
    from applypilot.scoring.scorer import _parse_score_response

    text = (
        "SCORE: 8\n"
        "RECOMMENDATION: apply\n"
        "KEYWORDS: python, kubernetes\n"
        "REASONING: Strong overlap.\n"
    )
    parsed = _parse_score_response(text)
    assert parsed["score"] == 8
    assert parsed["recommendation"] == "apply"
    assert "python" in parsed["keywords"]


@patch("applypilot.discovery.smartextract._run_one_site")
@patch("applypilot.discovery.agent_browse.run_agent_discover")
def test_smartextract_zero_job_agent_fallback(mock_agent, mock_one):
    from applypilot.discovery.smartextract import run_one_site_with_fallback

    mock_one.return_value = {"jobs": [], "status": "FAIL", "strategy": "none"}
    mock_agent.return_value = [
        {"url": "https://example.com/job", "title": "Engineer"},
    ]
    result = run_one_site_with_fallback(
        "TestSite",
        "https://example.com/careers",
        agent_fallback_enabled=True,
    )
    assert result["strategy"] == "agent_browse"
    assert len(result["jobs"]) == 1
    mock_agent.assert_called_once()


@patch("applypilot.discovery.runner._run_source")
def test_run_discover_respects_disabled_sources(mock_run):
    mock_run.return_value = {"status": "ok", "result": {}}

    def fake_config():
        return {
            "sources": {k: False for k in load_discover_config()["sources"]},
            "agent_discover": {"enabled": False, "max_pages": 1, "headless": True},
            "workatastartup": {},
            "hn_hiring": {},
            "himalayas": {},
            "remoteok": {},
        }

    with patch("applypilot.discovery.runner.load_discover_config", fake_config):
        from applypilot.discovery.runner import run_discover

        stats = run_discover(workers=1)
    assert stats == {}
    mock_run.assert_not_called()


def test_jobspy_search_applies_excluded_title_filter(monkeypatch):
    from applypilot.discovery import jobspy

    df = pd.DataFrame(
        [
            {
                "job_url": "https://jobs.example/staff-ai",
                "title": "Staff AI Engineer",
                "company": "Example",
                "location": "Bengaluru",
                "site": "linkedin",
            },
            {
                "job_url": "https://jobs.example/junior-qa",
                "title": "Junior QA Engineer",
                "company": "Example",
                "location": "Bengaluru",
                "site": "linkedin",
            },
        ]
    )

    stored_titles = []

    def fake_store(_conn, filtered_df, _source_label):
        stored_titles.extend(filtered_df["title"].tolist())
        return len(filtered_df), 0

    monkeypatch.setattr(jobspy, "_scrape_with_retry", lambda *_args, **_kwargs: df)
    monkeypatch.setattr(jobspy, "get_connection", lambda: object())
    monkeypatch.setattr(jobspy, "store_jobspy_results", fake_store)

    result = jobspy._run_one_search(
        {
            "query": "ai engineer",
            "location": "Bengaluru, Karnataka",
            "remote": False,
            "tier": 1,
        },
        ["linkedin"],
        10,
        72,
        None,
        {"country_indeed": "india"},
        0,
        ["bengaluru"],
        [],
        {},
        {"exclude_titles": ["Junior", "QA"]},
    )

    assert result["new"] == 1
    assert stored_titles == ["Staff AI Engineer"]


def test_parse_yc_companies_filters_batches_and_normalizes_websites():
    payload = [
        {"name": "Recent AI", "website": "recent.ai", "batch": "S25"},
        {"company_name": "OldCo", "website_url": "https://old.example/path", "yc_batch": "W20"},
        {"name": "No Site", "batch": "S25"},
    ]

    companies = parse_yc_companies(payload, batches=["S25"])

    assert companies == [
        {"name": "Recent AI", "website": "https://recent.ai", "batch": "S25"},
    ]


def test_career_sites_for_company_builds_smart_extract_targets():
    sites = career_sites_for_company(
        {"name": "Recent AI", "website": "https://www.recent.ai"},
        career_paths=["careers"],
        include_greenhouse=True,
    )

    assert sites[0] == {
        "name": "YC:Recent AI",
        "url": "https://www.recent.ai/careers",
        "type": "static",
        "mode": "smartextract",
        "source": "funded_startups",
    }
    assert {"https://boards.greenhouse.io/recent", "https://boards.greenhouse.io/recent-ai"} <= {
        site["url"] for site in sites
    }


@patch("applypilot.discovery.funded_startups.get_json")
def test_build_funded_startup_sites_uses_community_dataset(mock_get_json):
    mock_get_json.return_value = {
        "companies": [
            {"name": "Recent AI", "url": "recent.ai", "batch": "S25"},
            {"name": "Winter AI", "url": "https://winter.ai/about", "batch": "W25"},
        ]
    }

    sites = build_funded_startup_sites(
        {
            "batches": ["S25", "W25"],
            "limit": 2,
            "career_paths": ["jobs"],
            "include_greenhouse": False,
        }
    )

    assert [site["url"] for site in sites] == [
        "https://recent.ai/jobs",
        "https://winter.ai/jobs",
    ]


@patch("applypilot.discovery.runner.run_smart_extract")
@patch("applypilot.discovery.runner.load_sites", return_value=[])
@patch("applypilot.discovery.funded_startups.get_json")
def test_run_discover_feeds_funded_startups_to_smartextract(
    mock_get_json,
    _mock_load_sites,
    mock_smart_extract,
):
    mock_get_json.return_value = [
        {"name": "Recent AI", "website": "recent.ai", "batch": "S25"},
    ]
    mock_smart_extract.return_value = {"total_new": 0, "total_existing": 0, "passed": 0, "total": 1}

    def fake_config():
        cfg = load_discover_config()
        cfg["sources"] = {key: False for key in cfg["sources"]}
        cfg["sources"]["funded_startups"] = True
        cfg["sources"]["smartextract"] = True
        cfg["agent_discover"] = {"enabled": False, "max_pages": 1, "headless": True}
        cfg["funded_startups"] = {
            "batches": ["S25"],
            "limit": 1,
            "career_paths": ["careers"],
            "include_greenhouse": False,
        }
        return cfg

    with patch("applypilot.discovery.runner.load_discover_config", fake_config):
        from applypilot.discovery.runner import run_discover

        stats = run_discover(workers=1)

    assert stats["funded_startups"]["result"]["smartextract_sites"] == 1
    mock_smart_extract.assert_called_once()
    assert mock_smart_extract.call_args.kwargs["sites"] == [
        {
            "name": "YC:Recent AI",
            "url": "https://recent.ai/careers",
            "type": "static",
            "mode": "smartextract",
            "source": "funded_startups",
        }
    ]
