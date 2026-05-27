"""Archetype classification and template-based resume/cover-letter filling."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from applypilot.config import CONFIG_DIR, TEMPLATES_DIR, load_tailor_a_grade_config, templates_dir
from applypilot.scoring.keyword_extractor import keyword_overlap_ratio

log = logging.getLogger(__name__)

BUNDLED_ARCHETYPES_PATH = CONFIG_DIR / "templates_archetypes.yaml"

ARCHETYPE_RULES: list[tuple[str, str]] = [
    ("A8_eng_manager", r"\bengineering manager\b|\beng\s+manager\b|\bem\s+manager\b"),
    ("A6_founding", r"\bfounding engineer\b|\bfounder.?s\b"),
    (
        "A7_solutions",
        r"\b(solutions? engineer|solution engineer|forward deployed engineer|"
        r"customer engineer|partner engineer)\b",
    ),
    (
        "A4_ai_ml",
        r"\b(ai|ml|machine learning|applied ai|llm|gen ai)\s+engineer\b|\bml(ops)?\s+engineer\b",
    ),
    (
        "A5_staff",
        r"\b(staff|principal|distinguished)\s+(engineer|architect)\b|\bsoftware architect\b",
    ),
    (
        "A2_frontend_lead",
        r"\b(frontend|front[\s-]?end|ui)\s+(tech\s+lead|lead)\b|\blead\s+frontend\b",
    ),
    (
        "A1_senior_fe",
        r"\b(senior\s+)?(frontend|front[\s-]?end|ui|react)\s+(engineer|developer)\b",
    ),
    (
        "A3_full_stack",
        r"\b(senior\s+)?full[\s-]?stack\s+(engineer|developer)\b|\b(typescript|node\.?js)\s+developer\b",
    ),
]

DEFAULT_ARCHETYPE = "A3_full_stack"


def _archetypes_yaml_path() -> Path:
    return TEMPLATES_DIR / "archetypes.yaml"


def load_archetypes_config() -> dict[str, Any]:
    """Load archetypes YAML from ~/.applypilot/templates or bundled package defaults."""
    for path in (_archetypes_yaml_path(), BUNDLED_ARCHETYPES_PATH):
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except OSError as exc:
                log.warning("Could not read archetypes config %s: %s", path, exc)
                continue
            return data if isinstance(data, dict) else {}
    return {}


def classify_archetype(title: str, description: str = "") -> str:
    """Map job title + description snippet to an archetype id (deterministic)."""
    text = f"{title} {description[:500]}".lower()
    cfg = load_archetypes_config()
    rules = cfg.get("classifier_rules")
    if isinstance(rules, list) and rules:
        for entry in rules:
            if not isinstance(entry, dict):
                continue
            archetype_id = entry.get("id")
            pattern = entry.get("pattern")
            if archetype_id and pattern and re.search(pattern, text, re.I):
                return str(archetype_id)
    for archetype_id, pattern in ARCHETYPE_RULES:
        if re.search(pattern, text, re.I):
            return archetype_id
    return DEFAULT_ARCHETYPE


def is_a_grade_job(job: dict, profile: dict | None = None) -> bool:
    """True when job should use full LLM tailoring (high score or target company)."""
    cfg = load_tailor_a_grade_config(profile or {})
    min_score = int(cfg.get("min_score", 9))
    target_companies: set[str] = set(cfg.get("target_companies") or [])
    fit_score = job.get("fit_score") or 0
    site = (job.get("site") or "").strip().lower()
    if fit_score >= min_score:
        return True
    if site and site in target_companies:
        return True
    for company in target_companies:
        if company and company in site:
            return True
    return False


def _resume_template_path(archetype: str) -> Path:
    return TEMPLATES_DIR / "resumes" / f"{archetype}.txt"


def _cover_letter_template_path(archetype: str) -> Path:
    return TEMPLATES_DIR / "cover_letters" / f"{archetype}.txt"


def load_template_resume(archetype: str) -> str | None:
    path = _resume_template_path(archetype)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load_cover_letter_template(archetype: str) -> str | None:
    path = _cover_letter_template_path(archetype)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load_template_cover_letter(archetype: str) -> str | None:
    """Alias for load_cover_letter_template (cover letter template text)."""
    return load_cover_letter_template(archetype)


def load_keyword_pools() -> dict[str, list[str]]:
    """Per-archetype keyword lists from archetypes.yaml or keyword_pools.yaml."""
    cfg = load_archetypes_config()
    pools = cfg.get("keyword_pools")
    if isinstance(pools, dict):
        return {
            str(k): [str(x) for x in v if x]
            for k, v in pools.items()
            if isinstance(v, list)
        }
    pools_path = TEMPLATES_DIR / "keyword_pools.yaml"
    if pools_path.is_file():
        data = yaml.safe_load(pools_path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            return {
                str(k): [str(x) for x in v if x]
                for k, v in data.items()
                if isinstance(v, list)
            }
    archetypes = cfg.get("archetypes") or {}
    result: dict[str, list[str]] = {}
    if isinstance(archetypes, dict):
        for arch_id, meta in archetypes.items():
            if isinstance(meta, dict):
                seeds = meta.get("seed_keywords") or meta.get("keywords") or []
                if isinstance(seeds, list):
                    result[str(arch_id)] = [str(x) for x in seeds if x]
    return result


def fill_template(
    template_text: str,
    job: dict,
    keyword_pool: dict | None = None,
    archetype: str | None = None,
) -> str:
    """Substitute {company}, {role_title}, {keyword_1}, {keyword_2} placeholders."""
    pools = keyword_pool if keyword_pool is not None else load_keyword_pools()
    archetype = archetype or job.get("_archetype") or classify_archetype(
        job.get("title", ""), job.get("full_description") or ""
    )
    company = job.get("site") or "your company"
    role_title = job.get("title") or "this role"
    desc = (job.get("full_description") or "").lower()
    pool = pools.get(archetype, [])
    job_keywords = [kw for kw in pool if kw.lower() in desc][:2]

    filled = (
        template_text.replace("{company}", str(company))
        .replace("{role_title}", str(role_title))
        .replace("{keyword_1}", job_keywords[0] if job_keywords else "")
        .replace("{keyword_2}", job_keywords[1] if len(job_keywords) > 1 else "")
    )
    return filled


def keyword_density_ok(
    resume_text: str,
    job_description: str,
    threshold: float = 0.4,
) -> bool:
    """True when enough top job keywords appear in the resume text."""
    if not (job_description or "").strip():
        return True
    ratio = keyword_overlap_ratio(resume_text, job_description, top_n=15)
    return ratio >= threshold


def tailor_via_template(job: dict, profile: dict) -> tuple[str, dict] | None:
    """Fill a pre-built resume template; None if template file is missing."""
    archetype = classify_archetype(job.get("title", ""), job.get("full_description") or "")
    job = {**job, "_archetype": archetype}
    template_text = load_template_resume(archetype)
    if not template_text:
        return None
    filled = fill_template(template_text, job, load_keyword_pools(), archetype)
    report = {
        "status": "approved",
        "source": "template",
        "archetype": archetype,
        "attempts": 0,
        "validator": {"passed": True, "verdict": "TEMPLATE"},
        "judge": {"verdict": "SKIPPED", "passed": True, "issues": "template path"},
    }
    return filled, report


def cover_letter_via_template(job: dict, profile: dict) -> tuple[str, dict] | None:
    """Fill a pre-built cover letter template; None if template file is missing."""
    archetype = classify_archetype(job.get("title", ""), job.get("full_description") or "")
    job = {**job, "_archetype": archetype}
    template_text = load_cover_letter_template(archetype)
    if not template_text:
        return None
    filled = fill_template(template_text, job, load_keyword_pools(), archetype)
    report = {"source": "template", "archetype": archetype}
    return filled, report


def synthetic_job_for_archetype(archetype_id: str) -> dict:
    """Build a minimal job dict for one-shot LLM template bootstrap."""
    cfg = load_archetypes_config()
    archetypes = cfg.get("archetypes") or {}
    meta = archetypes.get(archetype_id, {}) if isinstance(archetypes, dict) else {}
    voice = ""
    title = archetype_id.replace("_", " ").title()
    if isinstance(meta, dict):
        voice = str(meta.get("voice") or "")
        title = str(meta.get("bootstrap_title") or meta.get("title") or title)
    description = voice or f"Ideal {title} role at a product-focused company."
    return {
        "title": title,
        "site": "Example Corp",
        "location": "Remote",
        "full_description": description,
        "url": f"template-bootstrap://{archetype_id}",
    }
