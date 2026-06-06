"""Match classified recruiter replies (LinkedIn + Gmail) to applied jobs."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from applypilot.apply import gmail_auth
from applypilot.database import get_connection, invalidate_stats_cache
from applypilot.inbox.intents import is_human_reply_intent, normalize_intent

_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "senior",
    "staff",
    "software",
    "engineer",
    "engineering",
    "product",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def company_candidates_from_job(job: dict[str, Any]) -> list[str]:
    """Reuse apply receipt heuristics for company matching."""
    return gmail_auth._job_company_candidates(job)


def company_candidates_from_hints(
    extracted_company: str | None,
    *,
    from_address: str = "",
    subject: str = "",
    snippet: str = "",
) -> list[str]:
    candidates: list[str] = []
    if extracted_company:
        candidates.append(extracted_company)
    blob = " ".join([from_address, subject, snippet])
    domain_match = re.search(r"@([a-z0-9.-]+\.[a-z]{2,})", blob.lower())
    if domain_match:
        host = domain_match.group(1)
        if host not in {"gmail.com", "googlemail.com", "outlook.com", "yahoo.com"}:
            candidates.append(host.split(".")[0])
    seen: set[str] = set()
    out: list[str] = []
    for raw in candidates:
        norm = _norm(raw)
        if len(norm) >= 2 and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def title_terms_from_job(job: dict[str, Any]) -> set[str]:
    title = _norm(str(job.get("title") or ""))
    return {part for part in title.split() if len(part) >= 4 and part not in _STOPWORDS}


def title_terms_from_hint(extracted_title: str | None) -> set[str]:
    title = _norm(extracted_title or "")
    return {part for part in title.split() if len(part) >= 4 and part not in _STOPWORDS}


def score_job_match(
    job: dict[str, Any],
    *,
    companies: list[str],
    title_hint: str | None,
    text_blob: str,
) -> float:
    blob = _norm(text_blob)
    if not blob:
        return 0.0

    job_companies = company_candidates_from_job(job)
    company_hit = any(c in blob for c in companies if c) or any(
        c in blob for c in job_companies if c
    )
    if not company_hit:
        return 0.0

    score = 0.55
    job_terms = title_terms_from_job(job)
    hint_terms = title_terms_from_hint(title_hint)
    if job_terms and hint_terms:
        overlap = job_terms & hint_terms
        if overlap:
            score += min(0.35, 0.15 * len(overlap))
    elif job_terms:
        overlap = {t for t in job_terms if t in blob}
        if len(overlap) >= min(2, len(job_terms)):
            score += 0.25

    app_url = str(job.get("application_url") or job.get("url") or "")
    host = urlparse(app_url).netloc.lower()
    if host and host.replace("www.", "") in blob.replace("www.", ""):
        score += 0.1

    return min(score, 1.0)


def _applied_jobs_for_matching(*, lookback_days: int) -> list[dict[str, Any]]:
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute(
        """
        SELECT url, title, site, location, application_url, applied_at, apply_status
        FROM jobs
        WHERE applied_at IS NOT NULL
          AND applied_at >= ?
          AND apply_status IN ('applied', 'submitted_unverified')
        ORDER BY applied_at DESC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def pick_best_job_match(
    jobs: list[dict[str, Any]],
    *,
    companies: list[str],
    title_hint: str | None,
    text_blob: str,
    min_score: float = 0.6,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for job in jobs:
        score = score_job_match(
            job,
            companies=companies,
            title_hint=title_hint,
            text_blob=text_blob,
        )
        if score > best_score:
            best_score = score
            best = {**job, "_match_score": score}
    if best and best_score >= min_score:
        return best
    return None


def record_job_reply(
    job_url: str,
    *,
    intent: str,
    channel: str,
    source_id: str,
    received_at: str | None = None,
) -> bool:
    """Write reply fields on jobs when a human recruiter reply is matched."""
    intent = normalize_intent(intent)
    if not is_human_reply_intent(intent):
        return False

    conn = get_connection()
    row = conn.execute(
        "SELECT reply_at FROM jobs WHERE url = ?",
        (job_url,),
    ).fetchone()
    if not row:
        return False

    reply_at = received_at or _utc_now()
    existing_at = row["reply_at"]
    if existing_at and str(existing_at) >= reply_at:
        return False

    conn.execute(
        """
        UPDATE jobs SET
            reply_status = ?,
            reply_at = ?,
            reply_channel = ?,
            reply_source_id = ?
        WHERE url = ?
        """,
        (intent, reply_at, channel, source_id, job_url),
    )
    conn.commit()
    invalidate_stats_cache()
    return True


def link_gmail_messages(*, lookback_days: int = 90) -> dict[str, int]:
    from applypilot.inbox.store import list_gmail_for_job_link

    jobs = _applied_jobs_for_matching(lookback_days=lookback_days)
    linked = 0
    skipped = 0
    for msg in list_gmail_for_job_link():
        intent = normalize_intent(msg.get("intent"))
        if not is_human_reply_intent(intent):
            skipped += 1
            continue
        text = " ".join(
            [
                msg.get("from_address") or "",
                msg.get("subject") or "",
                msg.get("snippet") or "",
            ]
        )
        companies = company_candidates_from_hints(
            msg.get("extracted_company"),
            from_address=msg.get("from_address") or "",
            subject=msg.get("subject") or "",
            snippet=msg.get("snippet") or "",
        )
        match = pick_best_job_match(
            jobs,
            companies=companies,
            title_hint=msg.get("extracted_title"),
            text_blob=text,
        )
        if not match:
            skipped += 1
            continue
        if record_job_reply(
            match["url"],
            intent=intent,
            channel="gmail",
            source_id=msg["message_id"],
            received_at=msg.get("received_at"),
        ):
            from applypilot.inbox.store import mark_gmail_matched

            mark_gmail_matched(msg["message_id"], match["url"])
            linked += 1
        else:
            skipped += 1
    return {"linked": linked, "skipped": skipped, "candidates": len(jobs)}


def link_linkedin_threads(*, lookback_days: int = 90) -> dict[str, int]:
    conn = get_connection()
    jobs = _applied_jobs_for_matching(lookback_days=lookback_days)
    rows = conn.execute(
        """
        SELECT t.conversation_urn, t.latest_inbound_text, t.last_inbound_at,
               o.intent, o.extracted_title, o.extracted_company
        FROM inbox_threads t
        JOIN inbox_opportunities o ON o.conversation_urn = t.conversation_urn
        WHERE o.intent IS NOT NULL
          AND o.classified_at IS NOT NULL
        ORDER BY t.last_inbound_at DESC
        """
    ).fetchall()

    linked = 0
    skipped = 0
    for row in rows:
        item = dict(row)
        intent = normalize_intent(item.get("intent"))
        if not is_human_reply_intent(intent):
            skipped += 1
            continue
        text = (item.get("latest_inbound_text") or "").strip()
        companies = company_candidates_from_hints(item.get("extracted_company"), snippet=text)
        match = pick_best_job_match(
            jobs,
            companies=companies,
            title_hint=item.get("extracted_title"),
            text_blob=text,
        )
        if not match:
            skipped += 1
            continue
        if record_job_reply(
            match["url"],
            intent=intent,
            channel="linkedin",
            source_id=item["conversation_urn"],
            received_at=item.get("last_inbound_at"),
        ):
            linked += 1
        else:
            skipped += 1
    return {"linked": linked, "skipped": skipped, "candidates": len(jobs)}


def link_all_replies(*, lookback_days: int = 90) -> dict[str, Any]:
    gmail = link_gmail_messages(lookback_days=lookback_days)
    linkedin = link_linkedin_threads(lookback_days=lookback_days)
    return {
        "gmail": gmail,
        "linkedin": linkedin,
        "linked": gmail["linked"] + linkedin["linked"],
    }
