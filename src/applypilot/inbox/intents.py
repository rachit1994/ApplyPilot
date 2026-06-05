"""Inbox message intent taxonomy and keyword pre-classification."""

from __future__ import annotations

import re

INTENT_APPLY_REQUEST = "apply_request"
INTENT_REJECTION = "rejection"
INTENT_STATUS_UPDATE = "status_update"
INTENT_INTERVIEW_INVITE = "interview_invite"
INTENT_AUTO_ACK = "auto_ack"
INTENT_SPAM = "spam"
INTENT_EDUCATION_PITCH = "education_pitch"
INTENT_OTHER = "other"

VALID_INTENTS = frozenset(
    {
        INTENT_APPLY_REQUEST,
        INTENT_REJECTION,
        INTENT_STATUS_UPDATE,
        INTENT_INTERVIEW_INVITE,
        INTENT_AUTO_ACK,
        INTENT_SPAM,
        INTENT_EDUCATION_PITCH,
        INTENT_OTHER,
    }
)

# Genuine human recruiter replies. Excludes spam / education pitches, automated
# "application received" acknowledgements, and the catch-all "other" bucket —
# none of those are evidence a human engaged, so counting them would inflate the
# reply-rate metric (WP-1) that the whole feature exists to measure.
HUMAN_REPLY_INTENTS = frozenset(
    {
        INTENT_APPLY_REQUEST,
        INTENT_REJECTION,
        INTENT_STATUS_UPDATE,
        INTENT_INTERVIEW_INVITE,
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

# High-precision only — interview_invite is never assigned from LLM alone.
_INTERVIEW_INVITE_PATTERNS = (
    r"schedule.{0,40}interview",
    r"interview.{0,40}schedule",
    r"invite.{0,30}interview",
    r"interview.{0,30}invite",
    r"phone screen",
    r"technical round",
    r"onsite interview",
    r"video interview",
    r"interview slot",
    r"interview availability",
    r"book.{0,20}interview",
)


# Automated submission acknowledgements (ATS "we received your application").
# These are NOT recruiter replies — the ATS senders (greenhouse/lever/...) the
# Gmail scan matches send them on every apply, so counting them double-counts the
# submission and makes reply-rate ≈ apply-rate for ATS sources.
_AUTO_ACK_PATTERNS = (
    r"we (?:have |'ve )?received your application",
    r"your application (?:has been|was|is) (?:received|submitted|under review)",
    r"thank you for (?:applying|your application|your interest in|submitting)",
    r"thanks for (?:applying|your application|your interest in)",
    r"application (?:has been |was )?received",
    r"we(?:'ve| have) got your application",
    r"successfully (?:applied|submitted your application)",
    r"this is an automated (?:message|response|confirmation|email)",
    r"(?:please )?do ?n['o]t reply to this (?:email|message)",
    r"application confirmation",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in patterns)


def looks_like_auto_acknowledgement(text: str) -> bool:
    """True for automated 'application received' acknowledgements (not a human reply).

    Interview-invite phrasing wins: an automated scheduler email is still a real
    next step, so those are never treated as auto-acks.
    """
    blob = (text or "").lower()
    if not blob:
        return False
    if _matches_any(blob, _INTERVIEW_INVITE_PATTERNS):
        return False
    return _matches_any(blob, _AUTO_ACK_PATTERNS)


def keyword_pre_classify(latest_inbound: str) -> dict | None:
    """Return {intent, confidence, source} when keywords are decisive, else None."""
    text = (latest_inbound or "").strip()
    if not text:
        return None

    if _matches_any(text, _INTERVIEW_INVITE_PATTERNS):
        return {"intent": INTENT_INTERVIEW_INVITE, "confidence": 0.93, "source": "keyword"}

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


def is_human_reply_intent(intent: str | None) -> bool:
    return normalize_intent(intent) in HUMAN_REPLY_INTENTS


def apply_interview_invite_precision_gate(
    intent: str,
    confidence: float,
    *,
    keyword_override: bool = False,
) -> tuple[str, float]:
    """Keep interview_invite only when keyword-backed (precision over recall)."""
    if normalize_intent(intent) != INTENT_INTERVIEW_INVITE:
        return intent, confidence
    if keyword_override:
        return INTENT_INTERVIEW_INVITE, confidence
    if confidence >= 0.92:
        return INTENT_INTERVIEW_INVITE, confidence
    return INTENT_STATUS_UPDATE, min(confidence, 0.75)
