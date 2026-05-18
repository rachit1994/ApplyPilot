"""Classify LinkedIn Other-tab threads by intent and apply-request signals."""

from __future__ import annotations

import json
import logging
import re

from applypilot.inbox.ats import apply_ats_boost, extract_ats_from_text
from applypilot.inbox.audit import log_event
from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.intents import (
    INTENT_APPLY_REQUEST,
    keyword_pre_classify,
    normalize_intent,
)
from applypilot.inbox.store import (
    get_thread_transcript,
    list_threads_for_classify,
    save_classification,
)
from applypilot.llm import get_gemini_client

logger = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = """You classify LinkedIn messaging threads from the "Other" inbox tab.
Return strict JSON only:
{
  "intent": "apply_request" | "rejection" | "status_update" | "spam" | "education_pitch" | "other",
  "confidence": number between 0 and 1,
  "extracted_title": string or null,
  "extracted_company": string or null,
  "reasoning": string (one short sentence)
}

Intent rules:
- apply_request: they ask the recipient to apply for an employment role or send CV/resume for a job
- rejection: not moving forward, filled role, poor fit, budget, visa/EP issues
- status_update: pipeline/review updates without a new apply ask
- education_pitch: MBA/MS/admissions/fellowship enrollment (not employment)
- spam: webinars, surveys, sales pitches
- other: everything else

Use "Latest inbound from them" as the primary signal."""


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def classify_thread_text(
    thread_text: str,
    *,
    client=None,
    threshold: float = 0.7,
    latest_inbound: str = "",
) -> dict:
    pre = keyword_pre_classify(latest_inbound)
    ats = extract_ats_from_text(thread_text)
    llm = client or get_gemini_client()
    user = f"Conversation (Other tab):\n\n{thread_text.strip()}\n"
    raw = llm.chat(
        messages=[
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=400,
    )
    data = _parse_json_object(raw)
    intent = normalize_intent(data.get("intent"))
    confidence = float(data.get("confidence") or 0)
    keyword_override = False

    if pre and pre["confidence"] >= 0.85:
        if pre["intent"] == "rejection" or intent == "rejection":
            intent = "rejection"
            confidence = max(confidence, pre["confidence"])
            keyword_override = True
        elif pre["intent"] == "education_pitch":
            intent = "education_pitch"
            confidence = max(confidence, pre["confidence"])
            keyword_override = True
        elif pre["intent"] == "apply_request" and intent != "rejection":
            intent = INTENT_APPLY_REQUEST
            confidence = max(confidence, pre["confidence"])
            keyword_override = True
        elif pre["intent"] in ("status_update", "spam") and intent not in (
            INTENT_APPLY_REQUEST,
            "rejection",
        ):
            intent = pre["intent"]
            confidence = max(confidence, pre["confidence"])
            keyword_override = True

    intent, confidence, ats_boosted = apply_ats_boost(
        intent=intent,
        confidence=confidence,
        apply_url=ats.get("apply_url"),
        latest_inbound=latest_inbound,
    )

    asked = intent == INTENT_APPLY_REQUEST and confidence >= threshold
    reasoning = str(data.get("reasoning") or "")
    if keyword_override:
        reasoning = f"{reasoning} [keyword:{pre['intent']}]".strip()
    if ats_boosted:
        reasoning = f"{reasoning} [ats:{ats.get('ats_vendor')}]".strip()

    return {
        "intent": intent,
        "intent_confidence": confidence,
        "asked_to_apply": asked,
        "is_job_related": asked,
        "confidence": confidence,
        "extracted_title": data.get("extracted_title"),
        "extracted_company": data.get("extracted_company"),
        "reasoning": reasoning,
        "apply_url": ats.get("apply_url"),
        "ats_vendor": ats.get("ats_vendor"),
        "keyword_override": keyword_override,
        "ats_boosted": ats_boosted,
    }


def classify_message(
    inbound_text: str,
    *,
    client=None,
    threshold: float = 0.7,
) -> dict:
    return classify_thread_text(
        f"Them: {inbound_text.strip()}",
        client=client,
        threshold=threshold,
        latest_inbound=inbound_text,
    )


def _thread_text_for_classification(thread: dict) -> tuple[str, str]:
    urn = thread["conversation_urn"]
    inbound = (thread.get("latest_inbound_text") or "").strip()
    preview = (thread.get("preview_text") or "").strip()
    transcript = get_thread_transcript(urn)
    parts: list[str] = []
    primary = inbound or preview
    if primary:
        parts.append(f"Latest inbound from them (primary signal):\n{primary}")
    if transcript:
        parts.append(f"\nFull thread (JSON-derived transcript):\n{transcript}")
    return "\n".join(parts), primary


def classify_inbox(*, settings: InboxSettings | None = None, limit: int | None = None) -> dict:
    cfg = settings or load_inbox_config()
    lim = limit if limit is not None else cfg.classify_limit
    client = get_gemini_client() if cfg.require_gemini else None

    classified = 0
    asked_to_apply = 0
    errors = 0

    for thread in list_threads_for_classify(lim, folder=cfg.inbox_folder):
        text, latest = _thread_text_for_classification(thread)
        if not text.strip():
            continue
        urn = thread["conversation_urn"]
        try:
            result = classify_thread_text(
                text,
                client=client,
                threshold=cfg.job_confidence_threshold,
                latest_inbound=latest,
            )
            save_classification(
                urn,
                is_job_related=result["asked_to_apply"],
                confidence=result["confidence"],
                extracted_title=result.get("extracted_title"),
                extracted_company=result.get("extracted_company"),
                reasoning=result["reasoning"],
                intent=result["intent"],
                intent_confidence=result.get("intent_confidence"),
                apply_url=result.get("apply_url"),
                ats_vendor=result.get("ats_vendor"),
            )
            log_event(
                urn,
                "classified",
                {
                    "intent": result["intent"],
                    "confidence": result["confidence"],
                    "asked_to_apply": result["asked_to_apply"],
                    "apply_url": result.get("apply_url"),
                    "ats_vendor": result.get("ats_vendor"),
                    "reasoning": result["reasoning"],
                    "keyword_override": result.get("keyword_override"),
                    "ats_boosted": result.get("ats_boosted"),
                },
            )
            classified += 1
            if result["asked_to_apply"]:
                asked_to_apply += 1
        except Exception as exc:
            logger.warning("Classify failed for %s: %s", urn, exc)
            log_event(urn, "classify_error", {"error": str(exc)})
            errors += 1

    return {
        "classified": classified,
        "asked_to_apply": asked_to_apply,
        "job_related": asked_to_apply,
        "errors": errors,
    }
