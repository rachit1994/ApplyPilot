"""Send eligibility rules for inbox job-reply."""

from __future__ import annotations

from applypilot.inbox.intents import is_apply_intent, normalize_intent


def should_skip_reply(
    thread: dict,
    opportunity: dict | None,
    *,
    require_unanswered: bool = True,
) -> str | None:
    """Return skip reason or None if send is allowed."""
    intent = normalize_intent((opportunity or {}).get("intent"))
    if opportunity and opportunity.get("intent"):
        if not is_apply_intent(intent):
            return "wrong_intent"
    elif not opportunity or not opportunity.get("is_job_related"):
        return "not_asked_to_apply"

    conf = float(opportunity.get("confidence") or 0)
    if conf <= 0:
        return "not_classified"

    if require_unanswered:
        inbound = thread.get("last_inbound_at") or ""
        outbound = thread.get("last_outbound_at") or ""
        if inbound and outbound and outbound >= inbound:
            return "outbound_is_latest"

    status = (thread.get("reply_status") or "").strip()
    if status == "sent":
        return "already_replied"

    return None


def is_eligible_for_draft(thread: dict, opportunity: dict | None) -> bool:
    skip = should_skip_reply(thread, opportunity)
    if skip in ("not_asked_to_apply", "wrong_intent"):
        return False
    if not opportunity or not (
        is_apply_intent(opportunity.get("intent")) or opportunity.get("is_job_related")
    ):
        return False
    status = thread.get("reply_status") or ""
    return status in ("", "pending", None) or status == "skipped"
