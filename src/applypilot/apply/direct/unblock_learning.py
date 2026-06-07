"""Self-learning wrapper around unblock.gemini_unblock — replay nav_playbook first."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

from applypilot.apply import apply_settings
from applypilot.apply.direct import extractor, unblock

logger = logging.getLogger(__name__)


class EscalationCapHit(Exception):
    """Per-family fail-rate cap tripped — structural wall, not a code bug."""


try:
    from applypilot.apply.direct import playbook as _playbook
except ImportError:  # pragma: no cover
    _playbook = None

try:
    from applypilot.apply.direct import review_log as _review_log
    from applypilot.database import get_connection as _get_connection
except ImportError:  # pragma: no cover
    _review_log = None
    _get_connection = None

# Navigation tools that must never replay from cache (submit carve-out).
_NEVER_REPLAY_TOOLS = frozenset({"submit", "finish"})
_DEFAULT_SCOPE = "host"
_FAMILY_SCOPE = "family"


def _nav_scope(_apex_host: str) -> str:
    return _DEFAULT_SCOPE


def _family_state_sig(before_snap: dict, *, family: str) -> str | None:
    """Family-scope signature (drops apex_host + step_name) for seed / generalized
    entries that apply across all tenants of an ATS family."""
    if _playbook is None:
        return None
    return _playbook.state_signature(
        before_snap, ats_family=family, apex_host=None, step_name=None
    )


def _snapshot_for_playbook(snap: dict) -> dict:
    """Strip runtime-only keys; keep fields playbook.state_signature expects."""
    out = {k: v for k, v in snap.items() if not k.startswith("_")}
    form = snap.get("_form")
    if form is not None:
        out.setdefault(
            "has_application_form",
            unblock._has_identity_form(form),
        )
    out.setdefault("has_cookie_banner", _cookie_banner_hint(snap))
    return out


def _cookie_banner_hint(snap: dict) -> bool:
    clickables = [str(c).lower() for c in (snap.get("clickables") or [])]
    cookie_markers = ("cookie", "consent", "onetrust", "accept all")
    return any(any(m in c for m in cookie_markers) for c in clickables)


def build_nav_snapshot(page) -> dict:
    """Page snapshot compatible with playbook.state_signature."""
    snap = unblock._snapshot(page)
    return _snapshot_for_playbook(snap)


def _entry_to_action(entry: Any) -> dict:
    if isinstance(entry, dict):
        tool = entry.get("action_type")
        raw_args = entry.get("action_args") or {}
    else:
        tool = getattr(entry, "action_type", None)
        raw_args = getattr(entry, "action_args", None) or {}
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    return {"tool": tool, "args": args}


def _replay_allowed(entry: Any) -> bool:
    if _playbook is None:
        return False
    action = _entry_to_action(entry)
    status = getattr(entry, "status", None) or (
        entry.get("status") if isinstance(entry, dict) else ""
    )
    return _playbook.is_replay_allowed(action.get("tool", ""), status or "")


def _action_replay_allowed(action: dict | None) -> bool:
    if not action:
        return False
    tool = (action.get("tool") or "").strip().lower()
    return tool not in _NEVER_REPLAY_TOOLS


def resolve_unblock_action(
    page,
    job: dict,
    *,
    family: str,
    apex_host: str,
    step_name: str = "",
    state_sig: str | None = None,
    family_sig: str | None = None,
) -> tuple[dict | None, str]:
    """Return (action, tier) where tier is 'replay' or 'gemini'."""
    _ = job
    if _playbook is None:
        return None, "gemini"

    scope = _nav_scope(apex_host)
    if state_sig is None:
        snap = build_nav_snapshot(page)
        state_sig = _playbook.state_signature(
            snap,
            ats_family=family,
            apex_host=apex_host or None,
            step_name=step_name or None,
        )
    if family_sig is None:
        family_sig = _family_state_sig(build_nav_snapshot(page), family=family)

    for tier_fn in _TIERS:
        action, tier = tier_fn(
            state_sig=state_sig or "",
            family_sig=family_sig,
            scope=scope,
        )
        if action is not None:
            return action, tier or "replay"
    return None, "gemini"


def _tier_host_replay(
    *,
    state_sig: str,
    family_sig: str | None,
    scope: str,
) -> tuple[dict | None, str | None]:
    entry = _playbook.lookup_nav(state_sig, scope=scope)
    if entry and _replay_allowed(entry):
        action = _entry_to_action(entry)
        if _action_replay_allowed(action):
            return action, "replay"
    return None, None


def _tier_family_replay(
    *,
    state_sig: str,
    family_sig: str | None,
    scope: str,
) -> tuple[dict | None, str | None]:
    _ = state_sig, scope
    if not family_sig:
        return None, None
    fam_entry = _playbook.lookup_nav(family_sig, scope=_FAMILY_SCOPE)
    if fam_entry and _replay_allowed(fam_entry):
        action = _entry_to_action(fam_entry)
        if _action_replay_allowed(action):
            return action, "replay"
    return None, None


def _tier_gemini(
    *,
    state_sig: str,
    family_sig: str | None,
    scope: str,
) -> tuple[dict | None, str | None]:
    _ = state_sig, family_sig, scope
    return None, "gemini"


# Ordered escalation ladder: host replay → family replay → Gemini.
_TIERS = (_tier_host_replay, _tier_family_replay, _tier_gemini)


def _state_advanced(before_snap: dict, after_snap: dict) -> bool:
    before_form = bool(before_snap.get("has_application_form"))
    after_form = bool(after_snap.get("has_application_form"))
    if after_form and not before_form:
        return True
    before_pw = bool(before_snap.get("has_password_field"))
    after_pw = bool(after_snap.get("has_password_field"))
    if before_pw and not after_pw:
        return True
    before_fields = len(before_snap.get("fields") or [])
    after_fields = len(after_snap.get("fields") or [])
    return after_fields > before_fields


def after_unblock_step(
    page,
    job: dict,
    *,
    family: str,
    apex_host: str,
    state_sig: str,
    action: dict | None,
    tier: str,
    result: str,
    before_snap: dict,
    after_snap: dict,
    step_name: str = "",
    step_index: int = 0,
) -> bool:
    """Record trial outcome and log to review_log. Returns whether state advanced."""
    _ = page
    if _playbook is None or not state_sig:
        return False

    scope = _nav_scope(apex_host)
    advanced = _state_advanced(before_snap, after_snap)

    if tier == "gemini" and action:
        _playbook.record_nav(
            state_sig,
            ats_family=family,
            apex_host=apex_host or None,
            step_name=step_name or None,
            action_type=(action.get("tool") or ""),
            action_args=action.get("args") or {},
            scope=scope,
            source="gemini",
        )

    if advanced:
        _playbook.bump_success(state_sig, scope=scope, weak=True)
    else:
        _playbook.bump_fail(state_sig, scope=scope)

    if _review_log is not None and _get_connection is not None:
        try:
            tool = (action or {}).get("tool")
            args = (action or {}).get("args") or {}
            _review_log.log_event(
                _get_connection(),
                job_url=job.get("url"),
                ats_family=family,
                apex_host=apex_host or None,
                state_sig=state_sig,
                scope=scope,
                step_index=step_index,
                url_before=before_snap.get("url"),
                url_after=after_snap.get("url"),
                tier=tier,
                action_type=tool,
                action_args=args,
                # Preserve the raw model decision for owner review ("what
                # Gemini suggested"), not just the parsed tool.
                llm_suggestion=(
                    json.dumps(action, ensure_ascii=False)
                    if tier == "gemini" and action else None
                ),
                outcome=result,
                postcondition_met=advanced,
            )
        except Exception:  # noqa: BLE001
            logger.debug("review_log.log_event failed", exc_info=True)
    return advanced


def _gemini_decide(page, job: dict, *, worker_id: int, history: list[str]) -> dict | None:
    from applypilot.llm import get_gemini_client

    snap = unblock._snapshot(page)
    prompt = (
        unblock._SYSTEM_PROMPT
        + "\n\nPAGE SNAPSHOT:\n"
        + unblock._snapshot_for_prompt(snap, job)
        + ("\n\nRECENT ACTIONS:\n" + " | ".join(history[-5:]) if history else "")
    )
    client = get_gemini_client()
    raw = client.ask(prompt, max_tokens=300, operation="apply_unblock")
    return unblock._parse_action(raw)


def apex_host_from_url(url: str | None) -> str:
    """Netloc for playbook state_signature / review_log."""
    if not url:
        return ""
    return urlsplit(str(url).strip()).netloc.lower()


def run_unblock_with_learning(
    page,
    job: dict,
    *,
    family: str,
    worker_id: int = 0,
    reason: str = "",
    max_steps: int = 8,
    apex_host: str = "",
    step_name: str = "",
    used_state_sigs: list[str] | None = None,
) -> bool:
    """Replay cached nav steps before Gemini; write back after each step.

    When ``used_state_sigs`` is provided, each resolved ``state_sig`` for a step
    is appended so callers can ``stamp_verified`` after end-to-end apply.
    """
    if not unblock.unblock_enabled():
        return False

    if not apex_host:
        apex_host = apex_host_from_url(getattr(page, "url", None) or job.get("url"))

    if _review_log is not None and _get_connection is not None:
        try:
            conn = _get_connection()
            cap_host = apex_host if family == "generic" else None
            attempts, fail_fraction = _review_log.recent_fail_rate(
                conn, ats_family=family, apex_host=cap_host
            )
            min_attempts = apply_settings.escalate_min_attempts()
            fail_rate = apply_settings.escalate_fail_rate()
            if attempts >= min_attempts and fail_fraction >= fail_rate:
                _review_log.log_event(
                    conn,
                    job_url=job.get("url"),
                    ats_family=family,
                    apex_host=apex_host or None,
                    tier="cap",
                    outcome="escalate_human",
                    failure_reason=(
                        f"fail_rate={fail_fraction:.2f} attempts={attempts}"
                    ),
                )
                logger.info(
                    "[W%d] Unblock capped for %s (%d attempts, %.0f%% fail)",
                    worker_id,
                    family,
                    attempts,
                    fail_fraction * 100,
                )
                raise EscalationCapHit(
                    f"escalation_cap:{family} "
                    f"fail_rate={fail_fraction:.2f} attempts={attempts}"
                )
        except EscalationCapHit:
            raise
        except Exception:  # noqa: BLE001
            logger.debug("escalation cap check failed", exc_info=True)

    unblock._dismiss_cookies(page)
    if unblock._has_identity_form(extractor.extract_fields(page)):
        return True

    logger.info(
        "[W%d] Unblock learning on %s (reason=%s)",
        worker_id,
        family,
        reason,
    )
    scope = _nav_scope(apex_host)
    history: list[str] = []
    for step in range(max_steps):
        snap = unblock._snapshot(page)
        if unblock._has_identity_form(snap["_form"]):
            logger.info("[W%d] Unblock learning: form ready after %d step(s)", worker_id, step)
            return True

        before_snap = _snapshot_for_playbook(snap)
        state_sig = ""
        family_sig = None
        if _playbook is not None:
            state_sig = _playbook.state_signature(
                before_snap,
                ats_family=family,
                apex_host=apex_host or None,
                step_name=step_name or None,
            )
            family_sig = _family_state_sig(before_snap, family=family)

        action, tier = resolve_unblock_action(
            page,
            job,
            family=family,
            apex_host=apex_host,
            step_name=step_name,
            state_sig=state_sig or None,
            family_sig=family_sig,
        )

        if tier == "replay" and action:
            tool = (action.get("tool") or "").lower()
            if tool == "finish":
                status = (action.get("args") or {}).get("status", "")
                ready = unblock._has_identity_form(extractor.extract_fields(page))
                if status == "blocked" or ready:
                    return ready
                history.append("replay finish rejected")
                page.wait_for_timeout(500)
                continue
            result = unblock._execute(page, action)
            history.append(f"replay:{tool}({action.get('args') or {}})->{result}")
            logger.info(
                "[W%d] Unblock replay step %d: %s -> %s",
                worker_id,
                step,
                tool,
                result,
            )
        else:
            try:
                action = _gemini_decide(page, job, worker_id=worker_id, history=history)
            except Exception as exc:  # noqa: BLE001
                if unblock._is_quota_error(exc):
                    raise unblock.GeminiQuotaExhausted(str(exc)) from exc
                logger.info("[W%d] Unblock learning: Gemini failed (%s)", worker_id, exc)
                return unblock._has_identity_form(extractor.extract_fields(page))
            if not action:
                return unblock._has_identity_form(extractor.extract_fields(page))
            tool = (action.get("tool") or "").lower()
            if tool == "finish":
                status = (action.get("args") or {}).get("status", "")
                ready = unblock._has_identity_form(extractor.extract_fields(page))
                if status == "blocked" or ready:
                    return ready
                history.append("finish(form_ready) rejected")
                page.wait_for_timeout(500)
                continue
            result = unblock._execute(page, action)
            history.append(f"gemini:{tool}({action.get('args') or {}})->{result}")
            logger.info(
                "[W%d] Unblock gemini step %d: %s -> %s",
                worker_id,
                step,
                tool,
                result,
            )
            tier = "gemini"

        page.wait_for_timeout(800)
        after_snap = build_nav_snapshot(page)
        advanced = after_unblock_step(
            page,
            job,
            family=family,
            apex_host=apex_host,
            state_sig=state_sig,
            action=action,
            tier=tier,
            result=result,
            before_snap=before_snap,
            after_snap=after_snap,
            step_name=step_name,
            step_index=step,
        )
        # Only steps whose own postcondition actually advanced are eligible for
        # end-to-end receipt credit (stamp_verified). This stops one successful
        # application from promoting incidental / no-op steps on its path.
        if (
            advanced
            and used_state_sigs is not None
            and state_sig
            and state_sig not in used_state_sigs
        ):
            used_state_sigs.append(state_sig)
        _ = scope  # reserved for multi-scope lookup later

    final = unblock._has_identity_form(extractor.extract_fields(page))
    logger.info("[W%d] Unblock learning: budget exhausted, form_ready=%s", worker_id, final)
    return final
