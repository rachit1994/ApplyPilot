"""Salary eligibility helpers for auto-apply."""

from __future__ import annotations

import re
from typing import Optional

DEFAULT_MIN_INR_ANNUAL = 4_000_000  # 40 LPA (apply + prompt default)
INDIA_MIN_INR_ANNUAL = 4_000_000
NON_INDIA_MIN_USD_ANNUAL = 70_000
_USD_TO_INR = 83


def get_min_annual_inr(profile: dict) -> int:
    comp = profile.get("compensation", {})
    currency = str(comp.get("salary_currency", "INR")).upper()
    for key in ("salary_range_min", "salary_expectation"):
        raw = str(comp.get(key, "")).replace(",", "").strip()
        if raw.isdigit():
            value = int(raw)
            if currency == "USD":
                return value * _USD_TO_INR
            return value
    return DEFAULT_MIN_INR_ANNUAL


def get_min_annual_usd(profile: dict | None = None) -> int:
    """USD floor for apply checks (fixed $70k; profile used only in form-fill prompts)."""
    _ = profile
    return NON_INDIA_MIN_USD_ANNUAL


def get_apply_floor_inr() -> int:
    """Hard apply eligibility floor for India roles (not profile compensation)."""
    return INDIA_MIN_INR_ANNUAL


def get_apply_floor_usd() -> int:
    return NON_INDIA_MIN_USD_ANNUAL


def _parse_inr_amount(raw: str) -> Optional[int]:
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0:
        return None
    if value < 1000:
        return int(value * 100_000)
    return int(value)


def _hourly_or_contract(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "/hr",
            " per hour",
            "hourly",
            "contract",
            "freelance",
            "/ monthly",
            " per month",
            "monthly intern",
        )
    )


def _bounds(amounts: list[int]) -> tuple[Optional[int], Optional[int]]:
    if not amounts:
        return None, None
    return min(amounts), max(amounts)


def _inr_from_token(number: str, unit: str) -> Optional[int]:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    if value <= 0:
        return None
    unit = unit.lower()
    if unit in ("m", "mm", "million"):
        return int(value * 1_000_000)
    if unit in ("k", "k_inr"):
        return int(value * 1_000)
    if unit in ("lpa", "lakh", "lakhs", "lac", "lacs", "l"):
        return int(value * 100_000)
    if value < 1000:
        return int(value * 100_000)
    return int(value)


def _extract_inr_bounds(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text or _hourly_or_contract(text):
        return None, None

    lowered = text.lower()
    amounts: list[int] = []

    for match in re.finditer(
        r"(?:₹|inr|rs\.?)\s*(\d+(?:\.\d+)?)\s*([MmKk]|lpa|lakhs?|lacs?|l)\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        amount = _inr_from_token(match.group(1), match.group(2))
        if amount is not None:
            amounts.append(amount)

    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*([Mm])\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        if "₹" not in lowered and "inr" not in lowered and "lpa" not in lowered:
            continue
        amount = _inr_from_token(match.group(1), match.group(2))
        if amount is not None:
            amounts.append(amount)

    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?)\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        amount = _inr_from_token(match.group(1), "lpa")
        if amount is not None:
            amounts.append(amount)

    if not amounts:
        for match in re.finditer(r"(\d{1,3}(?:,\d{2}){1,2}|\d{7,9})", lowered):
            if "$" in lowered[max(0, match.start() - 3) : match.start()]:
                continue
            amount = _parse_inr_amount(match.group(1))
            if amount is not None and amount >= 500_000:
                amounts.append(amount)

    return _bounds(amounts)


def _parse_usd_amount(raw: str) -> Optional[int]:
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0:
        return None
    if value < 1000:
        return int(value * 1000)
    return int(value)


def _extract_usd_bounds(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text or _hourly_or_contract(text):
        return None, None

    lowered = text.lower()
    amounts: list[int] = []
    if "₹" in lowered or " inr" in lowered or "lpa" in lowered:
        return None, None

    for match in re.finditer(
        r"(?:usd|\$)\s*(\d{2,3}(?:,\d{3})*(?:\.\d+)?|\d{2,3}(?:\.\d+)?)\s*(?:k\b)?",
        lowered,
        flags=re.IGNORECASE,
    ):
        amount = _parse_usd_amount(match.group(1))
        if amount is not None:
            amounts.append(amount)

    for match in re.finditer(
        r"\$\s*(\d{2,3}(?:,\d{3})+|\d{2,3})\s*(?:k\b)?",
        lowered,
        flags=re.IGNORECASE,
    ):
        amount = _parse_usd_amount(match.group(1))
        if amount is not None:
            amounts.append(amount)

    for match in re.finditer(r"(\d{2,3})k\s*(?:usd|\$)?", lowered, flags=re.IGNORECASE):
        amount = int(match.group(1)) * 1000
        amounts.append(amount)

    return _bounds(amounts)


def _extract_bounds(text: str) -> tuple[Optional[int], Optional[int]]:
    """Legacy INR-oriented bounds (profile min check); prefers INR then USD→INR."""
    inr_low, inr_high = _extract_inr_bounds(text)
    if inr_low is not None or inr_high is not None:
        return inr_low, inr_high
    usd_low, usd_high = _extract_usd_bounds(text)
    if usd_low is None and usd_high is None:
        return None, None
    return (
        usd_low * _USD_TO_INR if usd_low is not None else None,
        usd_high * _USD_TO_INR if usd_high is not None else None,
    )


def is_india_focused_job(
    location: str | None,
    description: str | None,
    salary_text: str | None,
) -> bool:
    blob = " ".join(part for part in (location, description, salary_text) if part).lower()
    if any(tok in blob for tok in ("₹", " inr", "rs.", "lpa", "lakhs", "lacs")):
        return True
    india_markers = (
        "india",
        "bengaluru",
        "bangalore",
        "karnataka",
        "hyderabad",
        "pune",
        "mumbai",
        "delhi",
        "gurgaon",
        "gurugram",
        "noida",
        "chennai",
        "remote (in",
        "in / remote",
    )
    us_markers = (
        "san francisco",
        "new york",
        "seattle",
        "boston",
        "austin",
        "los angeles",
        "united states",
        " u.s.",
        "usa",
        "remote (us",
        "remote us",
    )
    has_india = any(m in blob for m in india_markers)
    has_us = any(m in blob for m in us_markers)
    if has_us and not has_india:
        return False
    if has_india:
        return True
    if "$" in blob or " usd" in blob:
        return False
    return False


def salary_meets_regional_minimum(
    salary_text: str | None,
    description: str | None,
    location: str | None = None,
    *,
    profile: dict | None = None,
) -> bool:
    """India: max pay >= profile INR floor (default 50 LPA). Others: >= equivalent USD."""
    _ = profile
    min_inr = get_apply_floor_inr()
    min_usd = get_apply_floor_usd()
    combined = " ".join(
        part for part in (salary_text, description, location) if part
    )
    india = is_india_focused_job(location, description, salary_text)
    if india:
        _low, high = _extract_inr_bounds(combined)
        minimum = min_inr
    else:
        _low, high = _extract_usd_bounds(combined)
        minimum = min_usd

    if high is None:
        return True
    return high >= minimum


def salary_satisfies_minimum(
    salary_text: str | None,
    description: str | None,
    min_annual_inr: int,
) -> bool:
    combined = " ".join(part for part in (salary_text, description) if part)
    low, high = _extract_bounds(combined)
    if low is None and high is None:
        return True
    if high is not None and high < min_annual_inr:
        return False
    return True
