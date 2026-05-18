"""Inbox message intent taxonomy and keyword pre-classification."""

from __future__ import annotations

import re

INTENT_APPLY_REQUEST = "apply_request"
INTENT_REJECTION = "rejection"
INTENT_STATUS_UPDATE = "status_update"
INTENT_SPAM = "spam"
INTENT_EDUCATION_PITCH = "education_pitch"
INTENT_OTHER = "other"

VALID_INTENTS = frozenset(
    {
        INTENT_APPLY_REQUEST,
        INTENT_REJECTION,
        INTENT_STATUS_UPDATE,
        INTENT_SPAM,
        INTENT_EDUCATION_PITCH,
        INTENT_OTHER,
    }
)

_REJECTION_PATTERNS = (
    r"not moving forward",
    r"decided to proceed with other",
    r"position has been filled",
    r"unfortunately",
    r"after careful consideration",
    r"will not be moving forward",
    r"poor fit",
    r"not a fit",
    r"budget",
    r"experience.{0,20}mismatch",
)

_EDUCATION_PATTERNS = (
    r"\bmba\b",
    r"\bms\b",
    r"\bphd\b",
    r"fellowship",
    r"admissions",
    r"degree program",
    r"university",
    r"enroll",
    r"scholarship",
)

_STATUS_PATTERNS = (
    r"still reviewing",
    r"will keep you posted",
    r"in the pipeline",
    r"under review",
    r"next steps",
    r"follow up",
)

_SPAM_PATTERNS = (
    r"webinar",
    r"paid survey",
    r"exclusive offer",
    r"limited time",
)

_APPLY_PATTERNS = (
    r"please apply",
    r"apply here",
    r"send your cv",
    r"send your resume",
    r"share your cv",
    r"updated cv",
    r"application link",
    r"job posting",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in patterns)


def keyword_pre_classify(latest_inbound: str) -> dict | None:
    """Return {intent, confidence, source} when keywords are decisive, else None."""
    text = (latest_inbound or "").strip()
    if not text:
        return None

    if _matches_any(text, _REJECTION_PATTERNS):
        return {"intent": INTENT_REJECTION, "confidence": 0.92, "source": "keyword"}

    if _matches_any(text, _EDUCATION_PATTERNS):
        return {"intent": INTENT_EDUCATION_PITCH, "confidence": 0.9, "source": "keyword"}

    if _matches_any(text, _SPAM_PATTERNS):
        return {"intent": INTENT_SPAM, "confidence": 0.85, "source": "keyword"}

    if _matches_any(text, _STATUS_PATTERNS) and not _matches_any(text, _APPLY_PATTERNS):
        return {"intent": INTENT_STATUS_UPDATE, "confidence": 0.8, "source": "keyword"}

    if _matches_any(text, _APPLY_PATTERNS):
        return {"intent": INTENT_APPLY_REQUEST, "confidence": 0.88, "source": "keyword"}

    return None


def normalize_intent(raw: str | None) -> str:
    value = (raw or INTENT_OTHER).strip().lower()
    if value not in VALID_INTENTS:
        return INTENT_OTHER
    return value


def is_apply_intent(intent: str | None) -> bool:
    return normalize_intent(intent) == INTENT_APPLY_REQUEST
