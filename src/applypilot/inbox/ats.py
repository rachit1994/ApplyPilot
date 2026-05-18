"""Extract ATS apply URLs from LinkedIn inbox message text."""

from __future__ import annotations

import re
from typing import Any

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

_ATS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/[^\s<>\"')\]]+", re.I)),
    ("lever", re.compile(r"https?://jobs\.lever\.co/[^\s<>\"')\]]+", re.I)),
)


def mentions_apply_signal(text: str) -> bool:
    lower = (text or "").lower()
    signals = (
        "apply",
        "application",
        "cv",
        "resume",
        "job link",
        "job posting",
        "click here",
    )
    return any(s in lower for s in signals)


def extract_ats_from_text(text: str) -> dict[str, Any]:
    """Return {apply_url, ats_vendor} from message bodies."""
    blob = text or ""
    for vendor, pattern in _ATS_RULES:
        match = pattern.search(blob)
        if match:
            url = match.group(0).rstrip(".,;)")
            return {"apply_url": url, "ats_vendor": vendor}

    for raw in _URL_RE.findall(blob):
        cleaned = raw.rstrip(".,;)")
        lower = cleaned.lower()
        if "greenhouse.io" in lower:
            return {"apply_url": cleaned, "ats_vendor": "greenhouse"}
        if "lever.co" in lower:
            return {"apply_url": cleaned, "ats_vendor": "lever"}
    return {"apply_url": None, "ats_vendor": None}


def apply_ats_boost(
    *,
    intent: str,
    confidence: float,
    apply_url: str | None,
    latest_inbound: str,
) -> tuple[str, float, bool]:
    """Boost apply_request when ATS URL + apply language present. Returns (intent, confidence, boosted)."""
    if not apply_url or not mentions_apply_signal(latest_inbound):
        return intent, confidence, False
    if intent in ("rejection", "education_pitch", "spam"):
        return intent, confidence, False
    boosted_conf = max(confidence, 0.92)
    return "apply_request", boosted_conf, True
