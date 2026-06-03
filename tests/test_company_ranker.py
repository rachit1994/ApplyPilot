"""Tests for company-first discover ranking."""

from __future__ import annotations

from applypilot.discovery.company_ranker import (
    build_candidate_company_profile,
    rank_company_rows,
    rank_employer_map,
    seed_companies_from_profile,
)


PROFILE = {
    "experience": {
        "current_company": "Happening Today",
        "target_role": "Senior Full Stack Engineer",
    },
    "skills_boundary": {
        "languages": ["TypeScript", "Python"],
        "frameworks": ["React", "Node.js"],
        "tools": ["LangChain", "pgvector", "WebSockets"],
    },
    "resume_facts": {
        "preserved_companies": [
            "Happening Today",
            "MIRA",
            "Delta Exchange",
            "BetterPlace",
            "Liftoff Pvt Ltd",
            "Daffodils Software",
        ]
    },
}


def test_seed_companies_from_profile_uses_preserved_companies():
    assert seed_companies_from_profile(PROFILE) == [
        "Happening Today",
        "MIRA",
        "Delta Exchange",
        "BetterPlace",
        "Liftoff Pvt Ltd",
        "Daffodils Software",
    ]


def test_build_candidate_company_profile_infers_seed_traits():
    profile = build_candidate_company_profile(PROFILE)

    assert "ai" in profile.target_traits
    assert "rag" in profile.target_traits
    assert "fintech" in profile.target_traits
    assert "fullstack" in profile.target_traits


def test_rank_company_rows_prioritizes_seed_like_companies():
    rows = [
        {
            "name": "Generic Retail Careers",
            "careers_url": "https://retail.example/jobs",
            "ats": "custom",
        },
        {
            "name": "Semantic AI Agent Platform",
            "careers_url": "https://semantic-ai.example/careers",
            "ats": "greenhouse",
        },
        {
            "name": "Trading Risk Exchange",
            "careers_url": "https://trading-risk.example/jobs",
            "ats": "workday",
        },
    ]

    ranked = rank_company_rows(rows, profile=PROFILE)

    assert ranked[0]["name"] == "Semantic AI Agent Platform"
    assert ranked[0]["company_priority"] > ranked[-1]["company_priority"]
    assert "seed_like:" in ",".join(ranked[0]["company_priority_reasons"])
    assert "direct_apply_surface" in ranked[0]["company_priority_reasons"]


def test_rank_company_rows_keeps_job_boards_as_discovery_surfaces():
    rows = [
        {"name": "Unknown Board", "url": "https://unknown.example/jobs", "source": "sites_yaml"},
        {"name": "LinkedIn", "url": "https://linkedin.com/jobs/search", "source": "sites_yaml"},
        {"name": "Wellfound", "url": "https://wellfound.com/role/l/software-engineer", "source": "sites_yaml"},
    ]

    ranked = rank_company_rows(rows, profile=PROFILE)
    names = [row["name"] for row in ranked]

    assert names.index("LinkedIn") < names.index("Unknown Board")
    assert names.index("Wellfound") < names.index("Unknown Board")
    assert "company_discovery_board" in ranked[0]["company_priority_reasons"]


def test_rank_employer_map_preserves_keys_in_ranked_order():
    employers = {
        "plain": {
            "name": "Plain Careers",
            "tenant": "plain",
            "site_id": "External",
            "base_url": "https://plain.wd1.myworkdayjobs.com",
        },
        "fintech": {
            "name": "Fintech Trading Platform",
            "tenant": "fintech",
            "site_id": "External",
            "base_url": "https://fintech.wd1.myworkdayjobs.com",
        },
    }

    ranked = rank_employer_map(employers, profile=PROFILE)

    assert list(ranked) == ["fintech", "plain"]
    assert ranked["fintech"]["company_priority"] > ranked["plain"]["company_priority"]
