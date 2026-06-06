"""Pre-seed the Resolver Tier-1 Q&A bank from config/common_questions.yaml.

Deliberately LLM-free: token-backed rows resolve from the profile via
build_playbook_tokens (the same source the live Driver uses, so seeded answers
can never drift from runtime answers), and literal rows are curated constants.
Template rows store only the prompt — Gemini renders them at fill time, never
at seed time. So `applypilot seed-qa-bank` costs $0 and is safe to re-run.

    common_questions.yaml
        │  each row: label + answer_type + one of {token, literal, template}
        ▼
    build_playbook_tokens(profile, stub_job)   ← deterministic profile values
        │
        ▼
    qa_bank.store(label, answer, answer_type, section_header, source='seed')
"""

from __future__ import annotations

import logging

from applypilot import config
from applypilot.apply.direct import qa_bank

logger = logging.getLogger(__name__)

# build_playbook_tokens needs a job dict; these questions never reference
# job-specific tokens, so a stub with a placeholder URL is sufficient.
_STUB_JOB = {"url": "https://example.com/job", "application_url": ""}


def _load_questions() -> list[dict]:
    import yaml

    path = config.CONFIG_DIR / "common_questions.yaml"
    if not path.exists():
        raise FileNotFoundError(f"missing seed question file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not isinstance(questions, list):
        raise ValueError("common_questions.yaml: 'questions' must be a list")
    return questions


def _resolve_tokens() -> dict[str, str]:
    """Build the profile token map, tolerating an incomplete profile.

    A missing profile section means token-backed rows are skipped (we never
    seed an empty answer), but literal and template rows still seed.
    """
    try:
        profile = config.load_profile()
        from applypilot.apply.worker_playbook import build_playbook_tokens

        return build_playbook_tokens(
            profile, _STUB_JOB, resume_pdf_path="", cover_letter_pdf_path=""
        )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on bad profile
        logger.warning("Could not build profile tokens for seed: %s", exc)
        return {}


def seed_common_questions(*, dry_run: bool = False) -> int:
    """Seed (or preview) the curated Q&A set. Returns rows written/previewed.

    Idempotent: re-running refreshes answers in place (qa_bank.store upserts on
    the normalized key). Token rows whose profile value is empty are skipped.
    """
    questions = _load_questions()
    tokens = _resolve_tokens()
    written = 0

    for entry in questions:
        label = entry.get("label")
        if not label:
            continue
        answer_type = (entry.get("answer_type") or "text").strip().lower()
        section_header = entry.get("section_header")

        if "template" in entry:
            answer = str(entry["template"]).strip()
            answer_type = "template"
        elif "literal" in entry:
            answer = str(entry["literal"]).strip()
        elif "token" in entry:
            token_key = str(entry["token"]).strip()
            answer = (tokens.get(token_key) or "").strip()
            if not answer:
                logger.debug("Skipping %r — empty token %s", label, token_key)
                continue
        else:
            logger.debug("Skipping %r — no token/literal/template", label)
            continue

        if dry_run:
            written += 1
            continue

        qa_bank.store(
            label,
            answer,
            answer_type=answer_type,
            section_header=section_header,
            scope="generic",
            source="seed",
        )
        written += 1

    return written
