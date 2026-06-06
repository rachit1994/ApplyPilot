"""Gmail-backed employer verification codes for Direct Apply (Greenhouse/Airbnb wall)."""

from __future__ import annotations

import base64
import logging
import re
import time
from email.utils import parsedate_to_datetime

import httpx

from applypilot.apply import gmail_auth

logger = logging.getLogger(__name__)

_DEFAULT_CODE_RE = re.compile(r"\b[A-Z0-9]{6,8}\b")
_CODE_LABEL_RE = re.compile(r"(\d+)\s*[- ]?character", re.I)
_CODE_CONTEXT_RE = re.compile(
    r"(?:verification\s+code|security\s+code|one[- ]time\s+pass\s+code|pass\s+code|code)"
    r"[^A-Z0-9]{0,40}([A-Z0-9]{4,12})",
    re.I,
)


def infer_code_length(*, label: str = "", maxlength: str | int | None = None) -> int:
    """Best-effort code length from field metadata (default 8 for Greenhouse)."""
    if maxlength is not None:
        try:
            n = int(maxlength)
            if 4 <= n <= 12:
                return n
        except (TypeError, ValueError):
            pass
    m = _CODE_LABEL_RE.search(label or "")
    if m:
        try:
            n = int(m.group(1))
            if 4 <= n <= 12:
                return n
        except ValueError:
            pass
    return 8


def _code_pattern(length: int) -> re.Pattern[str]:
    lo = max(4, min(length, 12))
    hi = max(lo, min(length + 2, 12))
    return re.compile(rf"\b[A-Z0-9]{{{lo},{hi}}}\b")


def extract_code_from_text(text: str, *, code_length: int = 8) -> str | None:
    """Pick the most likely verification code from email body/snippet."""
    if not text:
        return None
    upper = text.upper()
    context_matches = [m.group(1).upper() for m in _CODE_CONTEXT_RE.finditer(upper)]
    if context_matches:
        exact_context = [m for m in context_matches if len(m) == code_length]
        if exact_context:
            return exact_context[0]
        return max(context_matches, key=len)
    pat = _code_pattern(code_length)
    matches = pat.findall(upper)
    if not matches:
        matches = _DEFAULT_CODE_RE.findall(upper)
    if not matches:
        return None
    if code_length <= 6:
        numeric_exact = [m for m in matches if len(m) == code_length and m.isdigit()]
        if numeric_exact:
            return numeric_exact[0]
    # Prefer exact length, else longest (codes are usually fixed-width).
    exact = [m for m in matches if len(m) == code_length]
    pool = exact or matches
    return max(pool, key=len)


def _message_epoch_s(message: gmail_auth.GmailMessageSummary) -> float:
    if not message.date:
        return 0.0
    try:
        return parsedate_to_datetime(message.date).timestamp()
    except (TypeError, ValueError, OSError):
        return 0.0


def _decode_body_data(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _collect_text_parts(payload: dict) -> str:
    """Flatten Gmail MIME payload into searchable plain text."""
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime.startswith("text/"):
        return _decode_body_data(data)
    chunks: list[str] = []
    for part in payload.get("parts") or []:
        chunk = _collect_text_parts(part)
        if chunk:
            chunks.append(chunk)
    return "\n".join(chunks)


def _fetch_message_bodies(
    summaries: list[gmail_auth.GmailMessageSummary],
) -> list[tuple[gmail_auth.GmailMessageSummary, str, float]]:
    """Return (summary, body_text, epoch_s) for messages after filtering."""
    token = gmail_auth._access_token()
    out: list[tuple[gmail_auth.GmailMessageSummary, str, float]] = []
    for summary in summaries:
        try:
            detail = httpx.get(
                f"{gmail_auth.GMAIL_API}/users/me/messages/{summary.message_id}",
                headers=gmail_auth._headers(token),
                params={"format": "full"},
                timeout=30.0,
            )
            detail.raise_for_status()
            data = detail.json()
            payload = data.get("payload") or {}
            body = _collect_text_parts(payload)
            snippet = str(data.get("snippet") or summary.snippet or "")
            text = body or snippet
            out.append((summary, text, _message_epoch_s(summary)))
        except Exception:  # noqa: BLE001
            logger.debug("Gmail body fetch failed for %s", summary.message_id, exc_info=True)
            out.append((summary, summary.snippet or "", _message_epoch_s(summary)))
    return out


def _matches_company_hint(text: str, company_hint: str) -> bool:
    hint = gmail_auth._norm(company_hint)
    if not hint or len(hint) < 2:
        return True
    blob = gmail_auth._norm(text)
    return hint in blob


def _build_search_query(company_hint: str) -> str:
    parts = [
        "newer_than:1h",
        "(subject:(verification OR code OR confirm OR identity) OR from:greenhouse OR from:ashbyhq)",
    ]
    hint = (company_hint or "").strip()
    if hint and len(hint) >= 2:
        parts.append(f'"{hint}"')
    return " ".join(parts)


def fetch_verification_code(
    *,
    company_hint: str = "",
    since_epoch_s: float,
    max_wait_s: float = 90.0,
    code_length: int = 8,
    poll_s: float = 5.0,
) -> str | None:
    """Poll Gmail for a recent employer verification code.

    Returns None when credentials are missing, no matching mail arrives in time,
    or no code can be parsed.
    """
    if not gmail_auth.credentials_exist():
        logger.info("Gmail credentials missing — cannot fetch verification code")
        return None

    deadline = time.monotonic() + max(0.0, max_wait_s)
    query = _build_search_query(company_hint)
    last_seen: set[str] = set()

    while time.monotonic() < deadline:
        try:
            summaries = gmail_auth._search_messages(query, limit=15)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gmail search failed: %s", exc)
            return None

        enriched = _fetch_message_bodies(summaries)
        enriched.sort(key=lambda row: row[2], reverse=True)

        for summary, text, epoch in enriched:
            if epoch and epoch < since_epoch_s - 30:
                continue
            blob = " ".join((summary.from_, summary.subject, text))
            if not _matches_company_hint(blob, company_hint):
                continue
            code = extract_code_from_text(text, code_length=code_length)
            if code and code not in last_seen:
                return code
            last_seen.add(code or "")

        time.sleep(max(1.0, poll_s))

    return None
