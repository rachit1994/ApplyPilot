"""Other-tab (SECONDARY) apply_request eligibility — single source of truth."""

from __future__ import annotations

from applypilot.inbox.config import InboxSettings, load_inbox_config
from applypilot.inbox.gates import should_skip_reply
from applypilot.inbox.intents import INTENT_APPLY_REQUEST, normalize_intent
from applypilot.inbox.store import list_threads_for_classify

OTHER_FOLDER = "other"
_BLOCKED_PUBLIC_IDS = frozenset({"", "linkedin-member"})


def opportunity_from_thread(thread: dict) -> dict:
    raw_intent = thread.get("intent")
    if raw_intent:
        intent = normalize_intent(raw_intent)
        is_apply = intent == INTENT_APPLY_REQUEST
    else:
        intent = None
        is_apply = bool(thread.get("is_job_related"))
    return {
        "is_job_related": is_apply,
        "confidence": thread.get("confidence"),
        "intent": intent or (INTENT_APPLY_REQUEST if is_apply else "other"),
    }


def is_secondary_inbox_thread(thread: dict) -> bool:
    return (thread.get("folder") or OTHER_FOLDER).strip().lower() == OTHER_FOLDER


def is_valid_public_id(public_id: str | None) -> bool:
    pid = (public_id or "").strip()
    if pid.lower() in _BLOCKED_PUBLIC_IDS:
        return False
    if pid.startswith("urn:") or pid.startswith("ACo"):
        return False
    return len(pid) > 2 and not pid.endswith("-")


def eligible_skip_reason(
    thread: dict,
    opportunity: dict | None,
    *,
    require_unanswered: bool = True,
) -> str | None:
    if not is_secondary_inbox_thread(thread):
        return "not_secondary_inbox"
    if not is_valid_public_id(thread.get("participant_public_id")):
        return "invalid_public_id"
    return should_skip_reply(thread, opportunity, require_unanswered=require_unanswered)


def is_apply_request_thread(thread: dict, opportunity: dict) -> bool:
    raw_intent = thread.get("intent")
    if raw_intent:
        return normalize_intent(raw_intent) == INTENT_APPLY_REQUEST
    return bool(opportunity.get("is_job_related"))


def list_eligible_other_threads(
    *,
    settings: InboxSettings | None = None,
    limit: int | None = None,
    require_unanswered: bool | None = None,
) -> list[dict]:
    cfg = settings or load_inbox_config()
    lim = limit if limit is not None else cfg.classify_limit
    unanswered = (
        cfg.require_unanswered_inbound
        if require_unanswered is None
        else require_unanswered
    )
    rows: list[dict] = []
    for thread in list_threads_for_classify(lim, folder=cfg.inbox_folder):
        opp = opportunity_from_thread(thread)
        if not is_apply_request_thread(thread, opp):
            continue
        if eligible_skip_reason(thread, opp, require_unanswered=unanswered):
            continue
        rows.append({**thread, **opp})
    return rows
