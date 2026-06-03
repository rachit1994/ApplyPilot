"""Company-first ranking for discover targets.

The first useful discover question is "which companies are likely to produce
fruitful jobs for this candidate?", not "which broad board can return the most
rows?". This module keeps the v1 ranking local, deterministic, and explainable
so it can safely drive source ordering before heavier ML exists.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from applypilot import config

log = logging.getLogger(__name__)


SEED_TRAITS: dict[str, set[str]] = {
    "happening today": {"ai", "rag", "agents", "events", "platform", "realtime"},
    "mira": {"ai", "generative_ai", "rag", "llm", "consumer", "scale"},
    "delta exchange": {"fintech", "trading", "crypto", "exchange", "realtime", "risk"},
    "betterplace": {"saas", "workforce", "enterprise", "automation", "compliance"},
    "liftoff pvt ltd": {"product_engineering", "services", "fullstack", "web"},
    "daffodils software": {"product_engineering", "services", "fullstack", "web"},
}

TRAIT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai": ("ai", "artificial intelligence", "machine learning", "ml"),
    "generative_ai": ("generative", "genai", "llm", "openai", "anthropic", "claude"),
    "rag": ("rag", "retrieval", "semantic", "vector", "search", "knowledge"),
    "agents": ("agent", "copilot", "automation", "workflow"),
    "fintech": ("fintech", "bank", "payments", "payment", "finance", "lending"),
    "trading": ("trading", "exchange", "market", "crypto", "risk", "derivatives"),
    "saas": ("saas", "enterprise", "b2b", "platform"),
    "workforce": ("workforce", "hr", "people", "compliance", "operations"),
    "product_engineering": ("product", "studio", "labs", "software", "engineering"),
    "fullstack": ("fullstack", "full-stack", "frontend", "backend", "developer"),
    "realtime": ("realtime", "real-time", "stream", "websocket", "event"),
    "scale": ("scale", "infrastructure", "cloud", "data", "platform"),
}

CURATED_COMPANY_TRAITS: dict[str, set[str]] = {
    "airbnb": {"saas", "platform", "scale", "product_engineering"},
    "anthropic": {"ai", "generative_ai", "llm", "agents"},
    "cursor": {"ai", "generative_ai", "product_engineering"},
    "datadog": {"saas", "platform", "scale", "realtime"},
    "figma": {"saas", "product_engineering", "scale"},
    "harvey": {"ai", "generative_ai", "product_engineering"},
    "linear": {"saas", "product_engineering"},
    "netflix": {"platform", "scale", "realtime"},
    "notion": {"saas", "ai", "product_engineering"},
    "openai": {"ai", "generative_ai", "llm", "agents"},
    "perplexity": {"ai", "generative_ai", "rag", "search"},
    "ramp": {"fintech", "payments", "saas"},
    "stripe": {"fintech", "payments", "platform", "scale"},
}

TECH_TRAIT_HINTS: dict[str, str] = {
    "react": "fullstack",
    "next.js": "fullstack",
    "node.js": "fullstack",
    "python": "scale",
    "aws": "scale",
    "langchain": "agents",
    "langgraph": "agents",
    "pgvector": "rag",
    "pinecone": "rag",
    "websockets": "realtime",
}

DISCOVERY_BOARD_PRIORS: dict[str, float] = {
    "linkedin": 0.18,
    "wellfound": 0.16,
    "greenhouse": 0.15,
    "lever": 0.14,
    "ashby": 0.14,
}


@dataclass(frozen=True)
class CandidateCompanyProfile:
    seed_companies: tuple[str, ...]
    target_traits: frozenset[str]
    target_roles: tuple[str, ...]


@dataclass(frozen=True)
class CompanyRank:
    name: str
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


def safe_load_profile() -> dict:
    """Load the user's profile, returning an empty profile if setup is missing."""
    try:
        return config.load_profile()
    except Exception as exc:
        log.debug("Company-first ranking without profile: %s", exc)
        return {}


def seed_companies_from_profile(profile: dict | None) -> list[str]:
    profile = profile or {}
    facts = profile.get("resume_facts") or {}
    companies = facts.get("preserved_companies") or []
    if not isinstance(companies, list):
        companies = []
    cleaned = [str(company).strip() for company in companies if str(company).strip()]

    current = ((profile.get("experience") or {}).get("current_company") or "").strip()
    if current and current.lower() not in {c.lower() for c in cleaned}:
        cleaned.insert(0, current)
    return cleaned


def build_candidate_company_profile(profile: dict | None = None) -> CandidateCompanyProfile:
    profile = profile if profile is not None else safe_load_profile()
    seed_companies = seed_companies_from_profile(profile)
    traits: set[str] = set()

    for company in seed_companies:
        traits.update(SEED_TRAITS.get(_norm(company), set()))

    skills = profile.get("skills_boundary") or {}
    for values in skills.values() if isinstance(skills, dict) else []:
        if not isinstance(values, list):
            continue
        for value in values:
            trait = TECH_TRAIT_HINTS.get(str(value).strip().lower())
            if trait:
                traits.add(trait)

    if not traits:
        traits.update({"fullstack", "product_engineering", "scale"})

    try:
        roles = tuple(config.get_target_roles(profile))
    except Exception:
        role = ((profile.get("experience") or {}).get("target_role") or "software engineer").strip()
        roles = (role,)

    return CandidateCompanyProfile(
        seed_companies=tuple(seed_companies),
        target_traits=frozenset(traits),
        target_roles=tuple(role for role in roles if role),
    )


def rank_company_rows(
    rows: Iterable[dict[str, Any]],
    *,
    profile: dict | None = None,
    source_history: Mapping[str, float] | None = None,
    max_rows: int = 0,
) -> list[dict[str, Any]]:
    """Return rows ordered by company-first probability."""
    candidate_profile = build_candidate_company_profile(profile)
    history = source_history or {}
    ranked: list[tuple[CompanyRank, int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        rank = score_company_row(row, candidate_profile, source_history=history)
        enriched = dict(row)
        enriched["company_priority"] = round(rank.score, 4)
        enriched["company_priority_reasons"] = list(rank.reasons)
        ranked.append((rank, index, enriched))

    ranked.sort(key=lambda item: (-item[0].score, item[1]))
    result = [row for _rank, _index, row in ranked]
    return result[:max_rows] if max_rows and max_rows > 0 else result


def rank_employer_map(
    employers: Mapping[str, dict[str, Any]],
    *,
    profile: dict | None = None,
    source_history: Mapping[str, float] | None = None,
    max_rows: int = 0,
) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, employer in employers.items():
        row = dict(employer)
        row["_employer_key"] = key
        row.setdefault("name", key)
        row.setdefault("ats", "workday")
        rows.append(row)

    ranked = rank_company_rows(
        rows,
        profile=profile,
        source_history=source_history,
        max_rows=max_rows,
    )
    return {
        str(row.pop("_employer_key")): row
        for row in ranked
        if row.get("_employer_key") is not None
    }


def score_company_row(
    row: Mapping[str, Any],
    candidate_profile: CandidateCompanyProfile,
    *,
    source_history: Mapping[str, float] | None = None,
) -> CompanyRank:
    name = _company_name(row)
    text = _row_text(row)
    row_traits = _traits_for_text(text)
    curated = CURATED_COMPANY_TRAITS.get(_norm(name), set())
    row_traits.update(curated)

    seed_similarity = _seed_similarity(name, row_traits, candidate_profile)
    tech_overlap = _trait_overlap(row_traits, candidate_profile.target_traits)
    role_density = _role_density_proxy(text, candidate_profile)
    applyability = _applyability_score(row)
    source_reward = _source_reward(row, source_history or {})
    board_prior = _board_prior(text)

    score = (
        0.32 * seed_similarity
        + 0.20 * role_density
        + 0.18 * tech_overlap
        + 0.16 * applyability
        + 0.09 * source_reward
        + 0.05 * board_prior
    )
    score = max(0.0, min(1.0, score))

    reasons = _rank_reasons(
        row_traits=row_traits,
        candidate_profile=candidate_profile,
        seed_similarity=seed_similarity,
        applyability=applyability,
        source_reward=source_reward,
        board_prior=board_prior,
    )
    return CompanyRank(name=name, score=score, reasons=tuple(reasons))


def load_source_history(days: int = 30) -> dict[str, float]:
    """Read existing source telemetry as a ranking hint. Fails closed."""
    if not config.DB_PATH.exists():
        return {}
    try:
        from applypilot.database import get_connection

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT
                source,
                SUM(discovered) AS discovered,
                SUM(scored_ge7) AS scored_ge7
            FROM discover_source_stats
            WHERE created_at >= datetime('now', ?)
            GROUP BY source
            """,
            (f"-{max(1, int(days))} days",),
        ).fetchall()
    except Exception as exc:
        log.debug("Company-first ranking without source history: %s", exc)
        return {}

    history: dict[str, float] = {}
    for row in rows:
        row_map = dict(row)
        source = str(row_map.get("source") or "").strip().lower()
        if not source:
            continue
        discovered = max(0, int(row_map.get("discovered") or 0))
        efficiency = (
            float(row_map.get("scored_ge7") or 0.0) / float(discovered)
            if discovered
            else 0.0
        )
        # Smooth tiny samples so a one-off source does not dominate.
        smoothed = (efficiency * discovered + 0.08 * 10) / (discovered + 10)
        history[source] = max(0.0, min(1.0, smoothed))
    return history


def _company_name(row: Mapping[str, Any]) -> str:
    for key in ("name", "company", "company_name", "site"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "Unknown"


def _row_text(row: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "name",
        "company",
        "company_name",
        "site",
        "url",
        "careers_url",
        "ats",
        "source",
        "greenhouse_board",
        "lever_site",
        "ashby_board",
        "ashby_site",
        "base_url",
    ):
        value = row.get(key)
        if value:
            values.append(str(value))
    return " ".join(values).lower()


def _traits_for_text(text: str) -> set[str]:
    traits: set[str] = set()
    for trait, keywords in TRAIT_KEYWORDS.items():
        if any(_contains_token(text, keyword) for keyword in keywords):
            traits.add(trait)
    return traits


def _seed_similarity(
    name: str,
    row_traits: set[str],
    candidate_profile: CandidateCompanyProfile,
) -> float:
    lowered = _norm(name)
    seed_names = {_norm(company) for company in candidate_profile.seed_companies}
    if lowered in seed_names:
        return 1.0
    if not candidate_profile.target_traits:
        return 0.0
    return _trait_overlap(row_traits, candidate_profile.target_traits)


def _trait_overlap(row_traits: set[str], target_traits: frozenset[str]) -> float:
    if not row_traits or not target_traits:
        return 0.0
    overlap = len(row_traits & set(target_traits))
    return min(1.0, overlap / max(3, min(len(target_traits), 8)))


def _role_density_proxy(text: str, candidate_profile: CandidateCompanyProfile) -> float:
    role_terms: set[str] = {"engineer", "developer", "platform", "backend", "frontend", "fullstack", "full-stack"}
    for role in candidate_profile.target_roles:
        role_terms.update(token for token in re.split(r"[^a-z0-9]+", role.lower()) if len(token) >= 3)
    hits = sum(1 for term in role_terms if term and term in text)
    return min(1.0, hits / 4)


def _applyability_score(row: Mapping[str, Any]) -> float:
    text = _row_text(row)
    ats = str(row.get("ats") or "").strip().lower()
    score = 0.0
    if ats in {"greenhouse", "lever", "ashby", "workday"}:
        score += 0.65
    if any(row.get(key) for key in ("greenhouse_board", "lever_site", "ashby_board", "ashby_site", "workday_key")):
        score += 0.25
    if any(marker in text for marker in ("greenhouse", "lever", "ashby", "workday", "careers", "jobs")):
        score += 0.15
    if any(marker in text for marker in ("linkedin", "wellfound")):
        score += 0.05
    return min(1.0, score)


def _source_reward(row: Mapping[str, Any], source_history: Mapping[str, float]) -> float:
    if not source_history:
        return 0.0
    candidates = {
        str(row.get("source") or "").strip().lower(),
        str(row.get("site") or "").strip().lower(),
        _company_name(row).strip().lower(),
    }
    for candidate in candidates:
        if candidate in source_history:
            return source_history[candidate]
    text = _row_text(row)
    for source, reward in source_history.items():
        if source and source in text:
            return reward
    return 0.0


def _board_prior(text: str) -> float:
    return max((prior for name, prior in DISCOVERY_BOARD_PRIORS.items() if name in text), default=0.0)


def _rank_reasons(
    *,
    row_traits: set[str],
    candidate_profile: CandidateCompanyProfile,
    seed_similarity: float,
    applyability: float,
    source_reward: float,
    board_prior: float,
) -> list[str]:
    reasons: list[str] = []
    overlap = sorted(row_traits & set(candidate_profile.target_traits))
    if seed_similarity >= 0.99:
        reasons.append("past_company_seed")
    elif overlap:
        reasons.append("seed_like:" + ",".join(overlap[:4]))
    if applyability >= 0.6:
        reasons.append("direct_apply_surface")
    elif applyability > 0:
        reasons.append("career_or_board_surface")
    if source_reward > 0:
        reasons.append(f"source_history:{source_reward:.2f}")
    if board_prior > 0:
        reasons.append("company_discovery_board")
    return reasons or ["cold_start_exploration"]


def _contains_token(text: str, keyword: str) -> bool:
    keyword = keyword.lower().strip()
    if not keyword:
        return False
    if re.search(r"[^a-z0-9]", keyword):
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
