"""Structured apply proof verification (Tier 1 ghost-fix gate)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerificationRecord:
    status: str                  # what the agent claimed
    submit_click_ref: str | None
    submit_button_text: str | None
    pre_submit_url: str | None
    post_submit_url: str | None
    post_submit_snapshot: dict[str, Any] | None
    confirmation_copy: str | None
    screenshot_path: str | None
    fill_actions: list[str]      # from apply_log_parser
    verification_code_used: str | None = None


@dataclass(frozen=True)
class Verdict:
    decision: str                # "verified" | "unverified" | "rejected"
    reasons: tuple[str, ...]     # human-readable; surfaced in dashboard


def evaluate(record: VerificationRecord) -> Verdict:
    if record.status != "applied":
        return Verdict(record.status, ())

    reasons: list[str] = []
    if not record.submit_click_ref or not record.submit_button_text:
        reasons.append("agent did not name a submit button it clicked")
    if not record.post_submit_url:
        reasons.append("no post-submit url observed")
    if record.pre_submit_url and record.post_submit_url == record.pre_submit_url \
            and not record.confirmation_copy:
        reasons.append("url unchanged after submit and no confirmation copy seen")
    if record.post_submit_snapshot is None:
        reasons.append("no post-submit form snapshot")
    if record.post_submit_snapshot and \
            record.post_submit_snapshot.get("fieldCount", 0) > 0 and \
            not record.confirmation_copy:
        reasons.append("form still rendered after submit")
    has_submit_tool_action = any("click" in a.lower() and (
            "send" in a.lower() or "submit" in a.lower() or "apply" in a.lower())
            for a in record.fill_actions)
    has_structured_submit_proof = bool(
        record.submit_click_ref
        and record.submit_button_text
        and record.confirmation_copy
        and record.post_submit_snapshot is not None
    )
    if not has_submit_tool_action and not has_structured_submit_proof:
        reasons.append("no browser_click on submit/send/apply tool action")

    if not reasons:
        return Verdict("verified", ())
    return Verdict("unverified", tuple(reasons))


def record_from_result_json(
    result_json: dict[str, Any],
    *,
    fill_actions: list[str] | None = None,
) -> VerificationRecord:
    return VerificationRecord(
        status=str(result_json.get("status", "failed")),
        submit_click_ref=result_json.get("submit_click_ref"),
        submit_button_text=result_json.get("submit_button_text"),
        pre_submit_url=result_json.get("pre_submit_url"),
        post_submit_url=result_json.get("post_submit_url"),
        post_submit_snapshot=result_json.get("post_submit_snapshot"),
        confirmation_copy=result_json.get("confirmation_copy"),
        screenshot_path=result_json.get("screenshot_path"),
        verification_code_used=result_json.get("verification_code_used"),
        fill_actions=list(fill_actions or []),
    )


def record_from_legacy_applied(
    *,
    fill_actions: list[str] | None = None,
) -> VerificationRecord:
    """Freeform RESULT:APPLIED with no structured proof fields."""
    return VerificationRecord(
        status="applied",
        submit_click_ref=None,
        submit_button_text=None,
        pre_submit_url=None,
        post_submit_url=None,
        post_submit_snapshot=None,
        confirmation_copy=None,
        screenshot_path=None,
        verification_code_used=None,
        fill_actions=list(fill_actions or []),
    )
