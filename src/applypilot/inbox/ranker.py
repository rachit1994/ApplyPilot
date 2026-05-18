"""Rank Other-tab apply_request threads with composite fit scoring."""

from __future__ import annotations

from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.eligibility import eligible_skip_reason, list_eligible_other_threads
from applypilot.inbox.intents import INTENT_APPLY_REQUEST


def confidence_to_fit_score(confidence: float | None) -> int:
    """Legacy mapping — prefer composite_fit_score for v2."""
    value = float(confidence or 0)
    if value <= 0:
        return 0
    return max(1, min(10, round(value * 10)))


def composite_fit_score(
    *,
    confidence: float,
    apply_url: str | None,
    extracted_title: str | None,
    extracted_company: str | None,
) -> tuple[int, dict]:
    """Return (fit_score 1-10, breakdown dict)."""
    base = round(float(confidence or 0) * 6)
    ats_pts = 2 if apply_url else 0
    title_pts = 1 if (extracted_title or "").strip() else 0
    company_pts = 1 if (extracted_company or "").strip() else 0
    total = base + ats_pts + title_pts + company_pts
    fit = max(1, min(10, total)) if total > 0 else 0
    breakdown = {
        "confidence_pts": base,
        "ats_pts": ats_pts,
        "title_pts": title_pts,
        "company_pts": company_pts,
    }
    return fit, breakdown


def build_ranked_queue(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
    require_unanswered: bool | None = None,
) -> list[dict]:
    """Return apply_request threads sorted by composite fit score (desc), then newest inbound."""
    cfg = settings or load_inbox_config()
    lim = limit if limit is not None else cfg.classify_limit
    unanswered = (
        cfg.require_unanswered_inbound
        if require_unanswered is None
        else require_unanswered
    )

    rows: list[dict] = []
    for thread in list_eligible_other_threads(
        settings=cfg, limit=lim, require_unanswered=unanswered
    ):
        opp = {
            "is_job_related": True,
            "confidence": thread.get("confidence"),
            "intent": thread.get("intent") or INTENT_APPLY_REQUEST,
        }
        skip = eligible_skip_reason(thread, opp, require_unanswered=unanswered)
        conf = float(opp.get("confidence") or 0)
        fit, breakdown = composite_fit_score(
            confidence=conf,
            apply_url=thread.get("apply_url"),
            extracted_title=thread.get("extracted_title"),
            extracted_company=thread.get("extracted_company"),
        )
        inbound = (thread.get("latest_inbound_text") or "").strip()
        preview = inbound[:100] + ("…" if len(inbound) > 100 else "")

        rows.append(
            {
                "conversation_urn": thread["conversation_urn"],
                "participant_public_id": thread.get("participant_public_id") or "",
                "fit_score": fit,
                "confidence": conf,
                "intent": opp["intent"],
                "apply_url": thread.get("apply_url"),
                "ats_vendor": thread.get("ats_vendor"),
                "extracted_title": thread.get("extracted_title"),
                "extracted_company": thread.get("extracted_company"),
                "reasoning": (thread.get("reasoning") or "").strip(),
                "last_inbound_at": thread.get("last_inbound_at") or "",
                "reply_status": thread.get("reply_status") or "",
                "approved_at": thread.get("approved_at"),
                "inbound_preview": preview,
                "eligible_to_send": skip is None,
                "skip_reason": skip,
                "score_breakdown": breakdown,
            }
        )

    rows.sort(
        key=lambda row: (row["fit_score"], row["last_inbound_at"] or ""),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows
