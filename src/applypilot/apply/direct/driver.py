"""Direct Apply Driver — deterministic, browser-driving apply with no LLM in the
hot loop.

Connects to the worker's already-running Chrome over CDP (the same browser the
Claude path uses), then runs the state machine:

    navigate ─► reveal form ─► extract ─► resolve ─► fill ─► upload resume
                                                              │
                          ┌───────────────────────────────────┘
                          ▼
        verify (no empty required, no blocking errors)
                          │
            dry_run? ──yes─► return skipped (nothing submitted)
                          │no
                          ▼
              submit ─► confirm success ─► applied

Iron rule: **never submit on uncertainty.** A partial/ambiguous form escalates
(to Claude rescue or a parked failure) rather than risk a junk submission in a
real employer's ATS. Escalation costs one cheap retry; a wrong submit is a
permanent quality defect.

The Driver returns a DriverResult the launcher maps onto its normal status
vocabulary; it also carries telemetry for the apply_outcomes ledger.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from applypilot import config
from applypilot.apply import apply_settings
from applypilot.apply.direct import extractor, fingerprint, profile_binding, resolver
from applypilot.apply.direct import captcha as direct_captcha
from applypilot.apply.direct import email_verify
from applypilot.apply.direct import unblock
from applypilot.apply.direct.adapters import Adapter, get_adapter
from applypilot.apply.prompt import ensure_resume_pdf
from applypilot.role_resumes import resolve_job_resume_path

logger = logging.getLogger(__name__)

# Tunables (kept conservative; humanization is volume-shaping, not impersonation).
_NAV_TIMEOUT_MS = 45_000
_FILL_DELAY = (0.15, 0.5)        # pause between fields
_SUBMIT_SETTLE_S = 6.0           # wait after submit click before reading result
_RESUME_LABEL_HINTS = ("resume", "cv", "résumé", "curriculum", "replace file")
_COVER_LABEL_HINTS = ("cover letter", "cover_letter", "coverletter")
_PHOTO_LABEL_HINTS = (
    "photo",
    "avatar",
    "headshot",
    "profile picture",
    "profile_photo",
    "image",
)
_TRANSIENT_SUBMIT_FRAGMENTS = (
    "something went wrong",
    "try again later",
    "please try again",
    "temporarily unavailable",
    "service unavailable",
    "internal server error",
    "gateway timeout",
)


def _is_transient_submit_error(messages: list[str]) -> bool:
    blob = " ".join(messages).lower()
    return any(frag in blob for frag in _TRANSIENT_SUBMIT_FRAGMENTS)


@dataclass
class DriverResult:
    result: str                     # launcher status string
    elapsed_ms: int = 0
    escalate: bool = False
    escalate_reason: str | None = None
    tier_resolved: int = 0
    fields_total: int = 0
    fields_llm: int = 0
    ats_family: str = ""
    fingerprint: str = ""


def _sleep_fill() -> None:
    time.sleep(random.uniform(*_FILL_DELAY))


def _job_url(job: dict) -> str:
    return str(job.get("application_url") or job.get("url") or "").strip()


def _canonical_apply_url(url: str, family: str) -> str:
    """Rewrite ATS-specific job URLs to the page that actually hosts the form.

    Greenhouse: custom-domain JD links → boards.greenhouse.io embed form.
    Workday: posting URLs without ``/apply`` only show the JD; the apply wizard
    lives at ``<posting>/apply`` (then Apply / Apply Manually).
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if family == "greenhouse":
        if "greenhouse.io" in parts.netloc.lower():
            return url
        from urllib.parse import parse_qs

        token = (parse_qs(parts.query).get("gh_jid") or [None])[0]
        if token:
            return f"https://boards.greenhouse.io/embed/job_app?token={token}"
        return url
    if family == "workday" and "myworkdayjobs.com" in parts.netloc.lower():
        path = parts.path.rstrip("/")
        low = path.lower()
        if "/job/" in low and "/apply" not in low:
            return f"{parts.scheme}://{parts.netloc}{path}/apply"
    return url


def _resume_pdf_path(job: dict) -> str | None:
    """Tailored resume if present, else the base resume (parity with --include-untailored)."""
    path = resolve_job_resume_path(job, allow_base=True)
    try:
        return str(ensure_resume_pdf(path))
    except (ValueError, OSError):
        return None


def _build_tokens(job: dict, resume_pdf: str) -> dict:
    from applypilot.apply.cover_resolve import resolve_apply_cover_letter
    from applypilot.apply.worker_playbook import build_playbook_tokens

    profile = config.load_profile()
    cl_text, _cl_txt, cover_pdf = resolve_apply_cover_letter(job)
    return build_playbook_tokens(
        profile,
        job,
        resume_pdf_path=resume_pdf,
        cover_letter_pdf_path=cover_pdf,
        cover_letter_text=cl_text,
    )


def _body_text_lower(page) -> str:
    try:
        return (page.inner_text("body") or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _embedded_resource_urls(page) -> tuple[str, ...]:
    """Collect iframe/script srcs so a custom-domain page's backing ATS (e.g. an
    embedded boards.greenhouse.io form) can be fingerprinted from content."""
    try:
        urls = page.eval_on_selector_all(
            "iframe[src], script[src]",
            "els => els.map(e => e.src).filter(Boolean)",
        )
        return tuple(dict.fromkeys(urls))
    except Exception:  # noqa: BLE001
        return ()


# Generic apply-control text for revealing a form on a custom career page whose
# ATS form only mounts after an Apply click (e.g. dropbox.jobs detail -> the
# greenhouse-backed apply page). Ordered most- to least-specific.
_GENERIC_APPLY_TEXTS = ("apply now", "apply for this job", "apply")


def _click_apply_to_reveal(page) -> bool:
    """Click a generic Apply link/button to surface a deferred ATS form.

    Some custom career sites render only the JD on the landing URL and load the
    real (ATS-backed) form on a separate apply page. Clicking Apply once lets the
    content-sniff see the backing ATS. Returns True if a control was clicked.
    """
    for text in _GENERIC_APPLY_TEXTS:
        for role in ("link", "button"):
            try:
                ctrl = page.get_by_role(role, name=text, exact=False).first
                if ctrl.count() > 0:
                    ctrl.click(timeout=5_000)
                    page.wait_for_timeout(2_500)
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _content_sniff_family(page) -> tuple[str, str | None]:
    """Sniff a loaded 'unknown' page for a known backing ATS.

    Returns (family, form_url). form_url, when set, is the hosted application
    form to re-navigate to (an embedded Greenhouse iframe) so the extractor —
    which does not descend into cross-origin iframes — can read it. family is
    'unknown' when no high-confidence marker is present, so the caller escalates.
    """
    urls = _embedded_resource_urls(page)
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        html = ""
    family = fingerprint.sniff_ats_family(html=html, embedded_urls=urls)
    if family in apply_settings.direct_excluded_families():
        return fingerprint.UNKNOWN_FAMILY, None
    form_url = fingerprint.greenhouse_form_url(urls) if family == "greenhouse" else None
    return family, form_url


# Labels that identify a *real* job-application form. If the engine fills a
# 2+-field form but lands on none of these, the page is almost certainly a
# search box / cookie banner / newsletter — NOT an application — so we must
# never submit it. Used by the identity-field safety guard below.
_IDENTITY_LABEL_HINTS: tuple[str, ...] = (
    "first name", "last name", "full name", "your name", "given name",
    "family name", "surname", "email", "e-mail", "phone", "mobile",
    "resume", "cv", "résumé", "linkedin",
)


def _identity_fields_filled(filled_rows: list[dict]) -> int:
    """Count filled rows whose label looks like a job-application identity field."""
    n = 0
    for row in filled_rows:
        if row.get("empty"):
            continue
        label = str(row.get("label") or "").lower()
        if any(hint in label for hint in _IDENTITY_LABEL_HINTS):
            n += 1
    return n


def _form_record_stub(
    url: str, job: dict, filled_rows: list[dict], errors: list[str]
) -> dict:
    """apply_form_filled record built outside the driver's main closure."""
    return {
        "form_url": url,
        "page_title": (job.get("title") or "")[:160],
        "company": job.get("site") or "",
        "fields": filled_rows,
        "fill_actions": [],
        "visible_errors": list(errors or []),
        "empty_required": 0,
        "field_count": len(filled_rows),
        "engine": "direct",
    }


def _record_row(label: str, value: str, *, ftype: str, via: str) -> dict:
    """One field row in the dashboard's apply_form_filled shape."""
    return {
        "label": label,
        "value": value,
        "type": ftype or "text",
        "empty": not str(value or "").strip(),
        "source": f"direct:{via}" if via else "direct",
    }


def _partition_checkbox_radio_groups(
    non_combo: list,
) -> tuple[dict[str, list], dict[str, list], list[str], list[str], set[str]]:
    """Group checkbox/radio fields for multi-option fill passes."""
    checkbox_groups: dict[str, list] = {}
    radio_groups: dict[str, list] = {}
    for f in non_combo:
        if f.type == "checkbox":
            group_key = ""
            if f.section_header:
                group_key = f"section:{f.section_header}"
            elif f.name_attr:
                group_key = f.name_attr
            if group_key:
                checkbox_groups.setdefault(group_key, []).append(f)
        if f.type == "radio" and f.name_attr:
            radio_groups.setdefault(f.name_attr, []).append(f)
    multi_group_keys = [k for k, v in checkbox_groups.items() if len(v) > 1]

    def _yes_no_option_pair(members: list) -> bool:
        labels = {m.label.strip().lower() for m in members}
        return labels == {"yes", "no"} or labels <= {"yes", "no", "n/a"}

    multi_radio_group_keys = [
        k for k, v in radio_groups.items()
        if len(v) > 1
        and (
            not _yes_no_option_pair(v)
            or any(m.section_header for m in v)
        )
    ]
    group_member_keys = {
        f.key for k in multi_group_keys for f in checkbox_groups[k]
    }
    group_member_keys.update(
        f.key for k in multi_radio_group_keys for f in radio_groups[k]
    )
    return (
        checkbox_groups,
        radio_groups,
        multi_group_keys,
        multi_radio_group_keys,
        group_member_keys,
    )


def _normalize_audit_label(label: str) -> str:
    return re.sub(r"[*#]+", "", (label or "").lower()).strip()


def _is_workday_progress_noise(field) -> bool:
    """Workday stepper widgets are not application fields."""
    label = _normalize_audit_label(getattr(field, "label", ""))
    tag = (getattr(field, "tag", "") or "").lower()
    if tag in {"ul", "ol", "nav"}:
        return True
    return bool(re.search(r"(completed )?step \d+ of \d+", label))


def _required_empty_fields(form_state) -> list:
    """Required fields still empty after fill (checkbox/radio groups handled)."""
    checked_group_names: set[str] = set()
    checked_group_sections: set[str] = set()
    for f in form_state.fields:
        if f.type == "checkbox" and str(f.value).strip():
            if f.name_attr:
                checked_group_names.add(f.name_attr)
            if f.section_header:
                checked_group_sections.add(f.section_header)
    checked_radio_names = {
        f.name_attr for f in form_state.fields
        if f.type == "radio" and f.name_attr and str(f.value).strip()
    }
    label_has_value = {
        _normalize_audit_label(f.label)
        for f in form_state.fields
        if str(f.value).strip()
    }
    return [
        f for f in form_state.fields
        if f.required and not f.combobox and not str(f.value).strip()
        and not _is_workday_progress_noise(f)
        and not (f.type == "checkbox" and f.name_attr in checked_group_names)
        and not (
            f.type == "checkbox"
            and f.section_header
            and f.section_header in checked_group_sections
        )
        and not (f.type == "radio" and f.name_attr in checked_radio_names)
        and _normalize_audit_label(f.label) not in label_has_value
    ]


def _radio_groups_from_form(form_state) -> dict[str, list]:
    groups: dict[str, list] = {}
    for f in form_state.fields:
        if f.type == "radio" and f.name_attr:
            groups.setdefault(f.name_attr, []).append(f)
    return groups


def _empty_radio_group_names(still_empty: list) -> set[str]:
    return {
        f.name_attr for f in still_empty
        if f.type == "radio" and f.name_attr
    }


_CLICK_RADIO_GROUP_JS = r"""({nameAttr, pick}) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const want = norm(pick);
  if (!nameAttr || !want) return false;
  const answerMatches = (txt) => {
    const t = norm(txt);
    return t === want || t.startsWith(want + ',') ||
      t.startsWith(want + ' ') || t.includes(want);
  };
  const inputs = [...document.querySelectorAll(`input[type="radio"][name="${nameAttr}"]`)];
  for (const el of inputs) {
    const txt = (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute('aria-label') || el.value || '';
    if (!answerMatches(txt)) continue;
    if (!el.checked) el.click();
    if (!el.checked) {
      el.checked = true;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    return !!el.checked;
  }
  return false;
}"""


def _radio_group_is_checked(page, name_attr: str) -> bool:
    if not name_attr:
        return False
    try:
        return bool(
            page.evaluate(
                """(nameAttr) => !!document.querySelector(
                  `input[type="radio"][name="${nameAttr}"]:checked`
                )""",
                name_attr,
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _click_radio_group_option(page, members, pick: str) -> bool:
    name_attr = members[0].name_attr if members else ""
    if not name_attr or not pick:
        return False
    try:
        return bool(
            page.evaluate(
                _CLICK_RADIO_GROUP_JS,
                {"nameAttr": name_attr, "pick": pick},
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("radio group DOM click failed for %r", name_attr, exc_info=True)
        return False


def _refill_empty_radio_groups(
    page,
    form_state,
    still_empty: list,
    *,
    tokens: dict,
    job: dict | None,
    gemini_enabled: bool,
    filled_rows: list[dict],
    outcome,
) -> None:
    """Re-fill required radio groups that verify still sees as empty."""
    empty_names = _empty_radio_group_names(still_empty)
    if not empty_names:
        return
    groups = _radio_groups_from_form(form_state)
    for name_attr in empty_names:
        members = groups.get(name_attr) or []
        if len(members) < 2:
            continue
        status, pick, via = _fill_radio_group(
            page,
            members,
            tokens=tokens,
            job=job,
            gemini_enabled=gemini_enabled,
        )
        if status == "filled" and pick:
            filled_rows.append(
                _record_row(
                    members[0].section_header or "radio group",
                    pick,
                    ftype="radio",
                    via=via or "group-retry",
                )
            )
            if outcome is not None:
                outcome.tier_max = max(outcome.tier_max, 0)


def _technology_groups_from_form(form_state) -> dict[str, list]:
    from applypilot.apply.direct import profile_binding

    groups: dict[str, list] = {}
    for f in form_state.fields:
        if f.type != "checkbox" or not f.section_header:
            continue
        if not profile_binding.is_technology_multi_checkbox_question(f.section_header):
            continue
        gkey = f"section:{f.section_header}"
        groups.setdefault(gkey, []).append(f)
    return {k: v for k, v in groups.items() if len(v) > 1}


def _technology_group_is_empty(members: list) -> bool:
    return not any(str(m.value).strip() for m in members)


def _refill_empty_technology_checkbox_groups(
    page,
    form_state,
    *,
    tokens: dict,
    job: dict | None,
    gemini_enabled: bool,
    filled_rows: list[dict],
    outcome,
) -> None:
    """Re-fill Lever technology multi-check groups cleared by resume upload."""
    groups = _technology_groups_from_form(form_state)
    for gkey, members in groups.items():
        if not _technology_group_is_empty(members):
            continue
        if not any(m.required for m in members):
            continue
        status, pick, via = _fill_technology_checkbox_group(
            page,
            members,
            tokens=tokens,
            job=job,
            gemini_enabled=gemini_enabled,
        )
        if status == "filled" and pick:
            filled_rows.append(
                _record_row(
                    members[0].section_header or "technology group",
                    pick,
                    ftype="checkbox",
                    via=via or "technology-retry",
                )
            )
            if outcome is not None:
                outcome.tier_max = max(outcome.tier_max, 0)


_FILL_TEXT_STABLE_JS = r"""({nameAttr, labelHint, value}) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const setVal = (el) => {
    if (!el) return false;
    const t = (el.type || '').toLowerCase();
    if (t === 'file' || t === 'checkbox' || t === 'radio' || t === 'hidden') return false;
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.blur();
    return !!String(el.value || '').trim();
  };
  if (nameAttr) {
    const el = document.querySelector(
      `input[name="${nameAttr}"], textarea[name="${nameAttr}"]`
    );
    if (setVal(el)) return true;
  }
  const want = norm(labelHint).replace(/^\*\s*/, '');
  if (!want) return false;
  for (const el of document.querySelectorAll('input, textarea')) {
    const t = (el.type || '').toLowerCase();
    if (['hidden', 'file', 'checkbox', 'radio'].includes(t)) continue;
    const lab = norm(
      (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute('aria-label') ||
      el.placeholder ||
      ''
    );
    if (!lab) continue;
    if (lab.includes(want) || want.includes(lab)) return setVal(el);
  }
  return false;
}"""


def _empty_text_fields(still_empty: list) -> list:
    return [
        f
        for f in still_empty
        if f.tag in {"input", "textarea"}
        and f.type not in {"file", "checkbox", "radio", "hidden"}
    ]


def _fill_text_field_stable(page, field, answer: str) -> bool:
    if not str(answer or "").strip():
        return False
    try:
        return bool(
            page.evaluate(
                _FILL_TEXT_STABLE_JS,
                {
                    "nameAttr": field.name_attr or "",
                    "labelHint": field.label or "",
                    "value": answer,
                },
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("stable text fill failed for %r", field.label, exc_info=True)
        return False


def _is_workday_search_field(field) -> bool:
    """Workday prompt-select widgets: plain text inputs with placeholder Search."""
    placeholder = (getattr(field, "placeholder", None) or "").strip().lower()
    blob = f"{field.label} {placeholder}".lower()
    if placeholder == "search":
        return True
    return any(
        m in blob
        for m in ("country phone code", "how did you hear", "hear about us")
    )


def _fill_workday_search_select(page, field, answer: str) -> bool:
    """Fill Workday autocomplete prompt-selects (Search placeholder)."""
    from applypilot.apply.direct import profile_binding

    label = field.label.replace("*", "").strip()
    try:
        inp = page.get_by_label(label, exact=False).first
        if inp.count() == 0:
            return False
        inp.scroll_into_view_if_needed(timeout=3_000)
        inp.click(timeout=4_000)
        inp.fill("")
        if profile_binding.is_source_question(field.label):
            for pref in profile_binding.PREFERRED_SOURCE_OPTIONS:
                inp.press_sequentially(pref[:24], delay=35, timeout=8_000)
                page.wait_for_timeout(900)
                for pick in profile_binding.PREFERRED_SOURCE_OPTIONS:
                    opt = page.get_by_role("option", name=pick, exact=False)
                    if opt.count() > 0:
                        opt.first.click(timeout=3_000)
                        page.wait_for_timeout(400)
                        if inp.input_value().strip():
                            return True
                inp.fill("")
        inp.press_sequentially(answer[:40], delay=35, timeout=8_000)
        page.wait_for_timeout(900)
        options = tuple(page.locator('[role="option"]').all_inner_texts())
        if not options:
            return bool(inp.input_value().strip())
        snapped = profile_binding.choose_select_option(answer, options) or options[0]
        opt = page.get_by_role("option", name=snapped, exact=False).first
        if opt.count() > 0:
            opt.click(timeout=3_000)
        page.wait_for_timeout(400)
        return bool(inp.input_value().strip())
    except Exception:  # noqa: BLE001
        logger.debug("workday search fill failed for %r", field.label, exc_info=True)
        return False


def _fill_workday_prompt_select(page, label_hint: str, answer: str) -> bool:
    """Fill a Workday prompt-select ('Select One') tied to a question label."""
    from applypilot.apply.direct import profile_binding

    if not str(answer or "").strip():
        return False
    needle = label_hint.strip().lower()[:80]
    try:
        clicked = page.evaluate(
            r"""({needle}) => {
              const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
              for (const root of document.querySelectorAll('[data-automation-id*="formField"]')) {
                const blob = norm(root.innerText);
                if (needle && !blob.includes(needle)) continue;
                const btn = [...root.querySelectorAll('button')].find(
                  (b) => norm(b.innerText).includes('select one')
                );
                if (!btn) continue;
                btn.scrollIntoView({ block: 'center' });
                btn.click();
                return true;
              }
              return false;
            }""",
            {"needle": needle.split(".")[0][:48]},
        )
        if not clicked:
            label = page.get_by_text(label_hint[:48], exact=False).first
            if label.count() == 0:
                return False
            root = label.locator('xpath=ancestor::*[contains(@data-automation-id,"formField")][1]')
            btn = root.get_by_role("button", name="Select One").first
            if btn.count() == 0:
                return False
            btn.scroll_into_view_if_needed(timeout=3_000)
            btn.click(timeout=4_000)
        page.wait_for_timeout(700)
        opts = tuple(page.locator('[role="option"]').all_inner_texts())
        pick = profile_binding.choose_select_option(answer, opts) if opts else answer
        for candidate in (pick, answer, "Yes", "No", "Not applicable"):
            if not candidate:
                continue
            opt = page.get_by_role("option", name=candidate, exact=False).first
            if opt.count() > 0:
                opt.click(timeout=3_000)
                page.wait_for_timeout(400)
                return True
    except Exception:  # noqa: BLE001
        logger.debug("workday prompt-select failed for %r", label_hint[:40], exc_info=True)
        return False
    return False


def _fill_workday_compliance_prompts(
    page,
    *,
    tokens: dict,
    filled_rows: list[dict],
) -> None:
    """BlackRock-style compliance prompt-selects on My Information."""
    from applypilot.apply.direct import profile_binding

    hints = (
        "legal authorization to work",
        "obtain, renew, extend or transfer a visa",
        "personal relationship",
    )
    for hint in hints:
        field = profile_binding.Field(
            label=hint,
            type="select",
            tag="button",
            name_attr="",
            section_header="",
            required=True,
            options=(),
            key=f"workday-prompt|{hint}",
        )
        res = profile_binding.resolve_field(field, tokens)
        if not res:
            continue
        if _fill_workday_prompt_select(page, hint, res.answer):
            filled_rows.append(
                _record_row(hint, res.answer, ftype="select", via=res.via or "workday:prompt")
            )
    _fill_workday_followup_textareas(page, tokens=tokens, filled_rows=filled_rows)


def _fill_workday_followup_textareas(
    page,
    *,
    tokens: dict,
    filled_rows: list[dict],
) -> None:
    """Fill conditional Workday textareas (e.g. visa sponsorship details)."""
    from applypilot.apply.direct import profile_binding

    form = extractor.extract_fields(page)
    still = _required_empty_fields(form)
    for f in _empty_text_fields(still):
        res = profile_binding.resolve_field(f, tokens)
        if not res:
            continue
        ok = _fill_text_field_stable(page, f, res.answer) or _fill_field(
            page, f, res.answer, family="workday",
        )
        if ok:
            filled_rows.append(
                _record_row(
                    f.label,
                    res.answer,
                    ftype=f.type or f.tag,
                    via=res.via or "workday:followup-text",
                )
            )


def _fill_workday_ack_checkboxes(page, filled_rows: list[dict]) -> None:
    """Required Workday acknowledgment checkboxes (Yes / I agree / I confirm)."""
    try:
        count = page.evaluate(
            r"""() => {
              const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
              let n = 0;
              for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                if (cb.checked || cb.disabled) continue;
                const label = norm(
                  (cb.labels && cb.labels[0] && cb.labels[0].innerText) ||
                  cb.getAttribute('aria-label') ||
                  ''
                );
                const req = !!(cb.required || cb.getAttribute('aria-required') === 'true');
                const ack = /^(yes\*?|i agree|i acknowledge|i confirm|accept|consent)/.test(label);
                if (!req && !ack) continue;
                cb.scrollIntoView({ block: 'center' });
                cb.click();
                n += 1;
              }
              return n;
            }"""
        )
        if count:
            filled_rows.append(
                _record_row("Acknowledgment", "Yes", ftype="checkbox", via="workday:ack")
            )
    except Exception:  # noqa: BLE001
        logger.debug("workday ack checkbox fill failed", exc_info=True)


def _fill_workday_voluntary_disclosures(
    page,
    *,
    tokens: dict,
    filled_rows: list[dict],
) -> None:
    """EEO / voluntary disclosures page (radios, prompt-selects, text, ack boxes)."""
    from applypilot.apply.direct import profile_binding

    _fill_workday_fieldset_radios(page, tokens=tokens, filled_rows=filled_rows)
    prompts = (
        "disability",
        "veteran",
        "gender",
        "race",
        "ethnicity",
        "citizen of another country",
        "permanent residency",
    )
    for hint in prompts:
        field = profile_binding.Field(
            label=hint,
            type="select",
            tag="button",
            section_header="Voluntary Disclosures",
            required=False,
            options=(),
            key=f"workday-voluntary|{hint}",
        )
        res = profile_binding.resolve_field(field, tokens)
        if not res:
            continue
        if _fill_workday_prompt_select(page, hint, res.answer):
            filled_rows.append(
                _record_row(hint, res.answer, ftype="select", via=res.via or "workday:voluntary")
            )
    _fill_workday_followup_textareas(page, tokens=tokens, filled_rows=filled_rows)
    form = extractor.extract_fields(page)
    still = _required_empty_fields(form)
    _refill_empty_text_fields(
        page,
        form,
        _empty_text_fields(still),
        tokens=tokens,
        job=None,
        gemini_enabled=False,
        filled_rows=filled_rows,
        outcome=None,
        family="workday",
    )
    _fill_workday_ack_checkboxes(page, filled_rows)


def _fill_workday_hear_about_us(page, answer: str = "LinkedIn") -> bool:
    """Workday hear-about widgets need a selected chip, not only typed search text."""
    from applypilot.apply.direct import profile_binding

    js = r"""({answer}) => {
      const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const want = norm(answer);
      let root = null;
      for (const el of document.querySelectorAll('label, legend, h3, p, span')) {
        const t = norm(el.innerText);
        if (!t.includes('how did you hear') && !t.includes('hear about us')) continue;
        root = el.closest('[data-automation-id*="formField"]')
          || el.closest('fieldset')
          || el.parentElement?.parentElement;
        if (root) break;
      }
      if (!root) return { ok: false, reason: 'no-root' };
      for (const cb of root.querySelectorAll('input[type="checkbox"]')) {
        const lbl = norm(
          (cb.labels && cb.labels[0] && cb.labels[0].innerText)
          || cb.getAttribute('aria-label') || ''
        );
        if (lbl.includes('linkedin') || lbl.includes(want)) {
          cb.click();
          if (cb.checked) return { ok: true, via: 'checkbox' };
        }
      }
      const inp = root.querySelector(
        'input[type="text"], input[placeholder*="earch" i], [role="combobox"] input'
      );
      if (!inp) return { ok: false, reason: 'no-input' };
      inp.focus();
      inp.click();
      inp.value = '';
      inp.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
      inp.value = answer;
      inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: answer, inputType: 'insertText' }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      let picked = false;
      for (const opt of document.querySelectorAll('[role="option"], li[data-automation-id*="option"]')) {
        const t = norm(opt.innerText);
        if (!t) continue;
        if (t.includes(want) || want.includes(t) || t.includes('linkedin')) {
          opt.click();
          picked = true;
          break;
        }
      }
      if (!picked) {
        inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
      }
      const chips = [...root.querySelectorAll(
        'ul li, [data-automation-id*="selected"], [class*="selectedItem"], [class*="multiSelect"]'
      )].map((el) => norm(el.innerText)).filter((t) => t && t !== 'items selected');
      const ok = chips.length > 0 || norm(inp.value).includes('linkedin');
      return { ok, chips, picked, via: picked ? 'option' : 'enter' };
    }"""
    try:
        result = page.evaluate(js, {"answer": answer})
        if isinstance(result, dict) and result.get("ok"):
            page.wait_for_timeout(500)
            return True
    except Exception:  # noqa: BLE001
        logger.debug("workday hear-about JS fill failed", exc_info=True)

    picks = profile_binding.PREFERRED_SOURCE_OPTIONS + (answer,)
    for pref in picks:
        if not pref:
            continue
        try:
            cb = page.get_by_role("checkbox", name=pref, exact=False).first
            if cb.count() > 0:
                cb.check(timeout=3_000)
                page.wait_for_timeout(400)
                return True
        except Exception:  # noqa: BLE001
            logger.debug("workday hear-about checkbox %r failed", pref, exc_info=True)
    form = extractor.extract_fields(page)
    for f in form.fillable():
        if profile_binding.is_source_question(f.label):
            if _fill_workday_search_select(page, f, answer):
                page.wait_for_timeout(400)
                return True
    return False


def _workday_advance_until_review(
    page,
    *,
    tokens: dict,
    filled_rows: list[dict],
    worker_id: int,
) -> None:
    """Clear validation errors and keep clicking Next until review/submit."""
    from applypilot.apply.direct.adapters import workday as wd_mod

    answer = str(tokens.get("referral_source") or tokens.get("hear_about") or "LinkedIn")
    for attempt in range(8):
        state = wd_mod.detect_workday_state(page.content())
        if state in {"review", "submit"}:
            return
        _workday_fix_validation_errors(page, tokens=tokens, filled_rows=filled_rows)
        _fill_workday_hear_about_us(page, answer)
        _fill_workday_compliance_prompts(page, tokens=tokens, filled_rows=filled_rows)
        _fill_workday_voluntary_disclosures(page, tokens=tokens, filled_rows=filled_rows)
        _fill_workday_phone_device_type(page)
        page.wait_for_timeout(600)
        if _workday_has_validation_errors(page):
            logger.info(
                "[W%d] Workday: validation errors remain (attempt %d)",
                worker_id,
                attempt + 1,
            )
            continue
        state = wd_mod.detect_workday_state(page.content())
        if state in {"review", "submit"}:
            return
        advance = _find_advance_button(page, family="workday")
        if not advance:
            return
        if not unblock._click_text(page, advance):
            return
        logger.info("[W%d] Workday: advanced via %r", worker_id, advance)
        page.wait_for_timeout(2_000)


def _workday_has_validation_errors(page) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => {
                  const norm = (s) => (s || '').toLowerCase();
                  for (const b of document.querySelectorAll('button, [role="button"]')) {
                    const t = norm(b.innerText || b.getAttribute('aria-label'));
                    if (t.includes('errors found') || t.startsWith('error-')) return true;
                  }
                  return false;
                }"""
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _fill_workday_phone_device_type(page) -> bool:
    """Workday 'Phone Device Type' prompt-select (Mobile / Home / Work)."""
    prefs = ("Mobile", "Cell Phone", "Mobile Phone", "Cell", "Personal Mobile")
    try:
        btn = page.locator('[data-automation-id*="phoneDevice"]').first
        if btn.count() == 0:
            label = page.get_by_text("Phone Device Type", exact=False).first
            if label.count() > 0:
                btn = label.locator("xpath=ancestor::div[1]").get_by_role("button").first
        if btn.count() == 0:
            btn = page.get_by_role("button", name="Select One").first
        if btn.count() == 0:
            return False
        btn.scroll_into_view_if_needed(timeout=3_000)
        btn.click(timeout=4_000)
        page.wait_for_timeout(700)
        for pref in prefs:
            opt = page.get_by_role("option", name=pref, exact=False).first
            if opt.count() > 0:
                opt.click(timeout=3_000)
                page.wait_for_timeout(400)
                return True
    except Exception:  # noqa: BLE001
        logger.debug("workday phone device type fill failed", exc_info=True)
        return False
    return False


def _workday_fix_validation_errors(
    page,
    *,
    tokens: dict,
    filled_rows: list[dict],
) -> None:
    """Re-fill Workday fields flagged by the inline Errors Found banner."""
    if not _workday_has_validation_errors(page):
        return
    from applypilot.apply.direct import profile_binding

    if _fill_workday_phone_device_type(page):
        filled_rows.append(
            _record_row("Phone Device Type", "Mobile", ftype="select", via="workday:device-type")
        )
    _fill_workday_hear_about_us(
        page,
        str(tokens.get("referral_source") or tokens.get("hear_about") or "LinkedIn"),
    )
    _fill_workday_compliance_prompts(page, tokens=tokens, filled_rows=filled_rows)
    _fill_workday_voluntary_disclosures(page, tokens=tokens, filled_rows=filled_rows)
    _fill_workday_followup_textareas(page, tokens=tokens, filled_rows=filled_rows)
    form = extractor.extract_fields(page)
    for f in form.fillable():
        blob = f"{f.label} {getattr(f, 'placeholder', '')}".lower()
        if _is_workday_search_field(f) or "phone device" in blob:
            res = profile_binding.resolve_field(f, tokens)
            if not res:
                continue
            if "phone device" in blob:
                if _fill_workday_phone_device_type(page):
                    filled_rows.append(
                        _record_row(f.label, res.answer, ftype=f.type or f.tag, via=res.via or "workday:device-type")
                    )
            elif _fill_workday_search_select(page, f, res.answer):
                filled_rows.append(
                    _record_row(f.label, res.answer, ftype=f.type or f.tag, via=res.via or "workday-search-retry")
                )
    page.wait_for_timeout(500)


def _workday_final_refill(
    page,
    *,
    tokens: dict,
    filled_rows: list[dict],
) -> None:
    """Last-pass refill on review/submit pages before pre-submit audit."""
    _workday_fix_validation_errors(page, tokens=tokens, filled_rows=filled_rows)
    _fill_workday_voluntary_disclosures(page, tokens=tokens, filled_rows=filled_rows)
    form = extractor.extract_fields(page)
    still = _required_empty_fields(form)
    _refill_workday_search_fields(page, still, tokens=tokens, filled_rows=filled_rows)
    _fill_workday_followup_textareas(page, tokens=tokens, filled_rows=filled_rows)
    _fill_workday_phone_device_type(page)
    page.wait_for_timeout(600)


def _refill_workday_search_fields(
    page,
    still_empty: list,
    *,
    tokens: dict,
    filled_rows: list[dict],
) -> None:
    from applypilot.apply.direct import profile_binding

    for f in still_empty:
        if not _is_workday_search_field(f):
            continue
        res = profile_binding.resolve_field(f, tokens)
        if not res:
            continue
        if _fill_workday_search_select(page, f, res.answer):
            filled_rows.append(
                _record_row(f.label, res.answer, ftype=f.type or f.tag, via=res.via or "workday-search")
            )


def _refill_empty_text_fields(
    page,
    form_state,
    still_empty: list,
    *,
    tokens: dict,
    job: dict | None,
    gemini_enabled: bool,
    filled_rows: list[dict],
    outcome,
    family: str,
) -> None:
    """Re-fill text inputs that verify still sees empty (common after resume upload)."""
    from applypilot.apply.direct import profile_binding

    retry_fields = _empty_text_fields(still_empty)
    if not retry_fields:
        return
    for f in retry_fields:
        res = profile_binding.resolve_field(f, tokens)
        ans = res.answer if res else None
        via = res.via if res else ""
        if not ans and gemini_enabled:
            sub = resolver.resolve(
                [f], tokens, job=job, gemini_enabled=True,
            )
            if outcome is not None:
                outcome.tier_max = max(outcome.tier_max, sub.tier_max)
                outcome.llm_field_count += sub.llm_field_count
            ans = sub.answers.get(f.key)
            via = sub.via.get(f.key, via)
        if not ans:
            continue
        ok = _fill_text_field_stable(page, f, ans) or _fill_field(
            page, f, ans, family=family,
        )
        if ok:
            filled_rows.append(
                _record_row(f.label, ans, ftype=f.type or f.tag, via=via or "text-retry")
            )
            if outcome is not None and res:
                outcome.tier_max = max(outcome.tier_max, 0)


_FILE_UPLOAD_AUDIT_JS = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const rows = [];
  document.querySelectorAll('input[type="file"]').forEach((el) => {
    const label = norm(
      (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.name ||
      el.id ||
      'file'
    );
    rows.push({
      label: label.slice(0, 120),
      name: norm(el.name || el.id || ''),
      required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      has_file: !!(el.files && el.files.length),
      file_name: (el.files && el.files[0] && el.files[0].name) || '',
    });
  });
  return rows;
}"""


def _audit_file_uploads(page) -> list[dict]:
    try:
        rows = page.evaluate(_FILE_UPLOAD_AUDIT_JS)
        return rows if isinstance(rows, list) else []
    except Exception:  # noqa: BLE001
        logger.debug("file upload audit failed", exc_info=True)
        return []


def _page_shows_filename(page, basename: str) -> bool:
    """Greenhouse clears ``input.files`` after S3 upload; filename stays in page text."""
    name = str(basename or "").strip()
    if not name or len(name) < 4:
        return False
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return name.lower() in body


def _enrich_audit_file_rows(
    audit_rows: list[dict],
    form,
    uploads: list[dict],
    *,
    resume_pdf: str,
    cover_pdf: str | None,
    page,
    family: str,
) -> None:
    """File inputs report empty DOM values; merge upload audit + intended paths."""
    field_by_label = {f.label: f for f in form.fillable()}
    accept_map = _file_accept_map(page)
    upload_by_name = {u.get("name", ""): u for u in uploads if u.get("name")}
    resume_basename = Path(resume_pdf).name if resume_pdf else ""
    cover_basename = Path(cover_pdf).name if cover_pdf else ""
    resume_on_page = _page_shows_filename(page, resume_basename)
    cover_on_page = _page_shows_filename(page, cover_basename) if cover_basename else False

    for row in audit_rows:
        if row.get("type") != "file":
            continue
        field = field_by_label.get(row.get("label") or "")
        name = (field.name_attr if field else "") or ""
        up = upload_by_name.get(name) or {}
        pseudo = {
            "label": row.get("label", ""),
            "name": name,
            "accept": accept_map.get(name, ""),
        }
        value = str(row.get("value") or "").strip()
        if not value and up.get("file_name"):
            value = str(up["file_name"])
        if _is_cover_file_upload(pseudo, family=family):
            if not value and cover_on_page and cover_basename:
                value = cover_basename
            elif not value and cover_pdf:
                value = str(cover_pdf)
        elif _is_resume_file_upload(pseudo, family=family):
            if not value and resume_on_page and resume_basename:
                value = resume_basename
            elif not value and resume_pdf:
                value = str(resume_pdf)
        row["value"] = value
        row["empty"] = not value

    has_resume_value = False
    for row in audit_rows:
        if row.get("type") != "file" or row.get("empty"):
            continue
        field = field_by_label.get(row.get("label") or "")
        name = (field.name_attr if field else "") or ""
        if _is_resume_file_upload(
            {"label": row.get("label", ""), "name": name, "accept": ""},
            family=family,
        ):
            has_resume_value = True
            break
    if resume_pdf and not has_resume_value:
        shown = str(resume_pdf)
        if resume_basename and resume_on_page:
            shown = f"{resume_basename} · {resume_pdf}"
        audit_rows.insert(
            0,
            _record_row("Resume (PDF)", shown, ftype="file", via="apply"),
        )


def _file_hint_is_cover(hint: str) -> bool:
    h = hint.lower()
    # Workable photo + resume slots use opaque input_files_* ids — not cover.
    if "input_files" in h:
        return False
    return any(token in h for token in _COVER_LABEL_HINTS)


def _file_hint_is_photo(hint: str) -> bool:
    h = hint.lower()
    return any(token in h for token in _PHOTO_LABEL_HINTS)


def _file_hint_is_resume(hint: str) -> bool:
    h = hint.lower()
    return any(token in h for token in _RESUME_LABEL_HINTS)


def _upload_accepts_images_only(accept: str) -> bool:
    a = (accept or "").lower().replace(" ", "")
    if not a:
        return False
    if "pdf" in a or ".doc" in a:
        return False
    image_markers = (
        "image/",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        "image/jpeg",
        "image/png",
    )
    return any(m in a for m in image_markers)


def _upload_accepts_documents(accept: str) -> bool:
    a = (accept or "").lower()
    return any(
        m in a
        for m in (".pdf", "pdf", ".doc", "doc", "application/pdf", "msword")
    )


def _is_cover_file_upload(pseudo: dict, *, family: str = "") -> bool:
    hint = f"{pseudo.get('label', '')} {pseudo.get('name', '')}".lower()
    if _file_hint_is_photo(hint) or _upload_accepts_images_only(
        pseudo.get("accept") or ""
    ):
        return False
    return _file_hint_is_cover(hint)


def _is_resume_file_upload(pseudo: dict, *, family: str = "") -> bool:
    hint = f"{pseudo.get('label', '')} {pseudo.get('name', '')}".lower()
    if _file_hint_is_photo(hint) or _upload_accepts_images_only(
        pseudo.get("accept") or ""
    ):
        return False
    if _is_cover_file_upload(pseudo, family=family):
        return False
    if _file_hint_is_resume(hint):
        return True
    if _upload_accepts_documents(pseudo.get("accept") or ""):
        return True
    if family == "workable" and "input_files" in hint:
        return True
    return True


def _pre_submit_audit(
    page,
    *,
    filled_rows: list[dict],
    resume_pdf: str,
    cover_pdf: str | None,
    worker_id: int,
    family: str,
) -> tuple[list[dict], list[dict], str | None]:
    """Re-read every form control from the DOM immediately before submit."""
    from applypilot.apply.direct import profile_binding

    form = extractor.extract_fields(page)
    still_empty = _required_empty_fields(form)
    filled_map = {r["label"]: r for r in filled_rows}
    filled_labels = {
        _normalize_audit_label(lbl)
        for lbl, row in filled_map.items()
        if str(row.get("value") or "").strip()
    }
    still_empty = [
        f for f in still_empty
        if _normalize_audit_label(f.label) not in filled_labels
    ]
    location_traps = [
        f for f in form.fillable()
        if profile_binding.is_yes_no_radiogroup(f)
        and profile_binding.is_location_requirement_trap(
            f"{f.section_header} {f.label}".strip()
        )
        and f.empty
    ]
    audit_rows: list[dict] = []
    for field in form.fillable():
        dom_value = str(field.value or "").strip()
        prev = filled_map.get(field.label)
        value = dom_value or str((prev or {}).get("value") or "").strip()
        via = "dom"
        if prev:
            src = str(prev.get("source") or "")
            via = src.replace("direct:", "", 1) if src.startswith("direct:") else src or "filled"
        audit_rows.append(
            _record_row(field.label, value, ftype=field.type or field.tag, via=via)
        )

    uploads = _audit_file_uploads(page)
    _enrich_audit_file_rows(
        audit_rows,
        form,
        uploads,
        resume_pdf=resume_pdf or "",
        cover_pdf=cover_pdf,
        page=page,
        family=family,
    )
    resume_name = Path(resume_pdf).name if resume_pdf else ""
    cover_name = Path(cover_pdf).name if cover_pdf else ""
    logger.info(
        "[W%d] Pre-submit audit (%s): %d field(s), resume=%s, cover=%s",
        worker_id,
        family,
        len(audit_rows),
        resume_name or "missing",
        cover_name or "none",
    )
    for row in audit_rows:
        shown = row["value"]
        if len(shown) > 140:
            shown = shown[:137] + "..."
        logger.info(
            "[W%d]   %s = %r (%s empty=%s via=%s)",
            worker_id,
            row["label"],
            shown,
            row["type"],
            row["empty"],
            row["source"],
        )

    if location_traps:
        labels = "; ".join(f.label[:80] for f in location_traps[:3])
        logger.info(
            "[W%d] Location requirement unmet (will not submit): %s",
            worker_id,
            labels,
        )
        return audit_rows, uploads, "not_eligible_location"

    accept_map = _file_accept_map(page)
    resume_attached = False
    cover_file_slots: list[dict] = []
    resume_inputs: list[dict] = []

    for up in uploads:
        hint = f"{up.get('label', '')} {up.get('name', '')}"
        pseudo = {
            "label": up.get("label", ""),
            "name": up.get("name", ""),
            "accept": accept_map.get(up.get("name", "") or "", ""),
            "required": up.get("required"),
        }
        if _file_hint_is_photo(hint) or _upload_accepts_images_only(pseudo["accept"]):
            continue
        logger.info(
            "[W%d]   upload %r required=%s has_file=%s file=%r",
            worker_id,
            up.get("label"),
            up.get("required"),
            up.get("has_file"),
            up.get("file_name"),
        )
        if _is_cover_file_upload(pseudo, family=family):
            cover_file_slots.append(up)
            fn = (up.get("file_name") or "").lower()
            if cover_name and cover_name.lower() in fn:
                logger.info("[W%d]   cover letter file attached on form", worker_id)
            continue
        if _is_resume_file_upload(pseudo, family=family):
            resume_inputs.append(up)
            fn = (up.get("file_name") or "").lower()
            if resume_name and resume_name.lower() in fn:
                resume_attached = True

    if resume_pdf and not resume_attached and resume_name:
        if _page_shows_filename(page, resume_name):
            resume_attached = True

    if resume_inputs and resume_pdf and not resume_attached:
        required_resume = any(up.get("required") for up in resume_inputs)
        if required_resume or len(resume_inputs) == 1:
            return audit_rows, uploads, "resume_not_uploaded"

    if cover_file_slots and cover_pdf and cover_name:
        cover_attached = any(
            cover_name.lower() in (up.get("file_name") or "").lower()
            for up in cover_file_slots
            if up.get("has_file")
        )
        if not cover_attached:
            return audit_rows, uploads, "cover_letter_not_uploaded"

    if still_empty:
        if profile_binding.remaining_gaps_are_location_traps(still_empty):
            return audit_rows, uploads, "not_eligible_location"
        blocking = "; ".join(f.label for f in still_empty[:10])
        return audit_rows, uploads, f"empty_required={blocking}"

    return audit_rows, uploads, None


def _persist_form_filled(url: str, record: dict) -> None:
    """Save the per-company filled-values record so the dashboard can show it."""
    try:
        import json as _json

        from applypilot.database import get_connection
        conn = get_connection()
        payload = _json.dumps(record, ensure_ascii=False)
        resume_path = str(record.get("resume_pdf") or "").strip()
        if resume_path:
            conn.execute(
                """
                UPDATE jobs
                SET apply_form_filled = ?, tailored_resume_path = ?
                WHERE url = ?
                """,
                (payload, resume_path, url),
            )
        else:
            conn.execute(
                "UPDATE jobs SET apply_form_filled = ? WHERE url = ?",
                (payload, url),
            )
        conn.commit()
    except Exception:  # noqa: BLE001
        logger.debug("persist form_filled failed for %s", url[:80], exc_info=True)


def _screenshot(page, worker_id: int, family: str) -> str:
    """Save a post-submit screenshot for evidence; return its path (or '')."""
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = config.LOG_DIR / f"direct_{ts}_w{worker_id}_{family}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:  # noqa: BLE001
        return ""


def _matches_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def _reveal_form(page, adapter: Adapter) -> None:
    """If the page shows the JD but no form yet, click the apply button."""
    form = extractor.extract_fields(page)
    if len(form.fillable()) >= 2:
        return
    for text in adapter.apply_button_texts:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if btn.count() == 0:
                btn = page.get_by_role("link", name=text, exact=False).first
            if btn.count() > 0:
                btn.click(timeout=5_000)
                page.wait_for_timeout(1_500)
                if len(extractor.extract_fields(page).fillable()) >= 2:
                    return
        except Exception:  # noqa: BLE001
            continue


def _wait_for_form_ready(page, *, timeout_ms: int = 8_000) -> None:
    """Wait for JS-rendered ATS forms to mount before declaring no_form.

    Ashby, Workable, and similar React apps often reach domcontentloaded while
    the application tab is still rendering. A fixed 1.2s wait is too short on
    real pages and causes a false no_form escalation even though the form
    appears a few seconds later.
    """
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        try:
            if len(extractor.extract_fields(page).fillable()) >= 2:
                return
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(500)


def _locator(page, field):
    if field.key:
        loc = page.locator(f'[data-ap-key="{field.key}"]').first
        if loc.count() > 0:
            return loc
    extractor.restamp(page, field)
    if field.key:
        loc = page.locator(f'[data-ap-key="{field.key}"]').first
        if loc.count() > 0:
            return loc
    return page.locator(f'[data-ap-id="{field.ap_id}"]').first


_CLICK_OPTION_NEAR_LABEL_JS = r"""({label, answer}) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wantLabel = norm(label).slice(0, 90);
  const wantAnswer = norm(answer).slice(0, 60);
  if (!wantLabel || !wantAnswer) return false;
  const answerMatches = (txt) => {
    const t = norm(txt);
    return t === wantAnswer || t.startsWith(wantAnswer + ',') ||
      t.startsWith(wantAnswer + ' ') || t.includes(wantAnswer);
  };
  const clickIfMatch = (root) => {
    const candidates = [
      ...root.querySelectorAll('button, [role="button"], label, [role="radio"], input[type="radio"], input[type="checkbox"]')
    ];
    for (const c of candidates) {
      const txt = c.innerText || c.value || c.getAttribute('aria-label') || '';
      if (answerMatches(txt)) {
        c.click();
        return true;
      }
    }
    return false;
  };
  const labels = [...document.querySelectorAll('label, legend, [id$="_label"], [class*="question-title"], [class*="Question"], [class*="label"], [class*="Label"]')];
  for (const lab of labels) {
    const txt = norm(lab.innerText).slice(0, 140);
    if (!txt || !(txt.includes(wantLabel) || wantLabel.includes(txt))) continue;
    let root = lab;
    for (let i = 0; i < 5 && root; i++, root = root.parentElement) {
      if (clickIfMatch(root)) return true;
    }
  }
  return false;
}"""


def _click_option_near_label(page, field, answer: str) -> bool:
    try:
        return bool(
            page.evaluate(
                _CLICK_OPTION_NEAR_LABEL_JS,
                {"label": field.label, "answer": answer},
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("option click fallback failed for %r", field.label, exc_info=True)
        return False


_CLICK_LEVER_SECTION_CHECKBOX_JS = r"""({sectionHint, optionLabel}) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const wantSec = norm(sectionHint).replace(/[\u2731✱]/g, '').slice(0, 100);
  const wantOpt = norm(optionLabel);
  if (!wantSec || !wantOpt) return false;
  const secMatches = (txt) => {
    const t = norm(txt).replace(/[\u2731✱]/g, '');
    return t.includes(wantSec.slice(0, 40)) || wantSec.includes(t.slice(0, 40));
  };
  const optMatches = (txt) => {
    const t = norm(txt);
    return t === wantOpt || t.includes(wantOpt) || wantOpt.includes(t);
  };
  const labels = [...document.querySelectorAll('.application-label')];
  for (const block of labels) {
    const txtNode = block.querySelector('.text') || block;
    if (!secMatches(txtNode.innerText || '')) continue;
    let el = block;
    for (let i = 0; i < 24 && el; i++) {
      el = el.nextElementSibling;
      if (!el) break;
      if (el.classList && el.classList.contains('application-label')) break;
      const inputs = el.querySelectorAll('input[type="checkbox"]');
      for (const inp of inputs) {
        const ltxt = (inp.labels && inp.labels[0] && inp.labels[0].innerText) ||
          inp.getAttribute('aria-label') || inp.value || '';
        if (!optMatches(ltxt)) continue;
        if (!inp.checked) inp.click();
        if (!inp.checked) {
          inp.checked = true;
          inp.dispatchEvent(new Event('input', {bubbles: true}));
          inp.dispatchEvent(new Event('change', {bubbles: true}));
        }
        return !!inp.checked;
      }
    }
  }
  return false;
}"""


def _click_lever_section_checkbox(page, section: str, option_label: str) -> bool:
    if not section or not option_label:
        return False
    try:
        return bool(
            page.evaluate(
                _CLICK_LEVER_SECTION_CHECKBOX_JS,
                {"sectionHint": section, "optionLabel": option_label},
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "lever section checkbox click failed for %r / %r",
            section[:40],
            option_label,
            exc_info=True,
        )
        return False


_CHECKBOX_DOM_CLICK_JS = r"""({key, apId}) => {
  let el = null;
  if (key) el = document.querySelector(`[data-ap-key="${key}"]`);
  if (!el && apId !== undefined && apId !== null) {
    el = document.querySelector(`[data-ap-id="${apId}"]`);
  }
  if (!el || (el.type || '').toLowerCase() !== 'checkbox') return false;
  if (!el.checked) el.click();
  if (!el.checked) {
    el.checked = true;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  return !!el.checked;
}"""


def _check_checkbox_dom(page, field) -> bool:
    try:
        return bool(
            page.evaluate(
                _CHECKBOX_DOM_CLICK_JS,
                {"key": field.key, "apId": field.ap_id},
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("checkbox DOM click failed for %r", field.label, exc_info=True)
        return False


def _ashby_visible_option_field(field) -> bool:
    blob = f"{field.label} {field.section_header}".lower()
    return any(
        marker in blob
        for marker in (
            "authorized to work",
            "legally authorized",
            "sponsorship",
            "sponsor",
            "immigration case",
            "sponsor my employment",
            "hybrid",
            "anchor days",
            "working from one of our offices",
            "work from the office",
            "in person",
        )
    )


def _fill_field_legacy(page, field, answer: str, *, family: str = "") -> bool:
    """Legacy fill path (used when field_strategy has no cached method)."""
    try:
        loc = _locator(page, field)
        if loc.count() == 0:
            return False
        loc.scroll_into_view_if_needed(timeout=3_000)
        if field.tag == "select":
            try:
                loc.select_option(label=answer)
            except Exception:  # noqa: BLE001
                loc.select_option(value=answer)
            return True
        if field.options:
            from applypilot.apply.direct import profile_binding

            pick = profile_binding.choose_select_option(answer, field.options)
            if not pick:
                return False
            scoped = page.locator(f'[data-ap-key="{field.key}"]').first
            radio = scoped.get_by_role("radio", name=pick, exact=False).first
            if radio.count() == 0:
                radio = page.get_by_role("radio", name=pick, exact=False).first
            if radio.count() == 0:
                return False
            radio.click(timeout=4_000)
            return True
        if field.type == "radio":
            from applypilot.apply.direct import profile_binding

            if profile_binding.choose_select_option(answer, (field.label,)) == field.label:
                if family == "ashby":
                    return _click_option_near_label(page, field, answer)
                try:
                    loc.check(timeout=3_000)
                    return True
                except Exception:  # noqa: BLE001
                    return _click_option_near_label(page, field, answer)
            return False
        if field.type == "checkbox":
            want = answer.strip().lower() in ("yes", "true", "checked", "on", "1")
            if want:
                if family == "ashby" and _ashby_visible_option_field(field):
                    return _click_option_near_label(page, field, answer)
                try:
                    loc.check(timeout=3_000)
                except Exception:  # noqa: BLE001
                    if _check_checkbox_dom(page, field):
                        return True
                    return _click_option_near_label(page, field, answer)
                # Styled checkboxes (e.g. Greenhouse "I acknowledge") wrap a
                # visually-hidden input; .check() reports success but the bound
                # state never flips. Confirm, and click the label if it didn't.
                try:
                    if not loc.is_checked():
                        if _check_checkbox_dom(page, field):
                            return True
                        return _click_option_near_label(page, field, answer)
                except Exception:  # noqa: BLE001
                    pass
            return True
        if field.type == "number":
            digits = re.sub(r"[^0-9.]+", "", answer)
            if digits:
                answer = digits
        if field.type == "tel":
            # intl-tel-input detects the country from keystrokes, not a bulk
            # value set; typing the E.164 number makes it format/validate as the
            # right country instead of an over-long US number. Click to focus
            # (forces the widget to attach), clear, type, then blur to finalize.
            loc.click(timeout=4_000)
            page.wait_for_timeout(200)
            loc.fill("", timeout=5_000)
            loc.press_sequentially(answer, delay=30, timeout=8_000)
            page.wait_for_timeout(200)
            try:
                loc.blur()
            except Exception:  # noqa: BLE001
                pass
            return True
        loc.fill(answer, timeout=5_000)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("fill failed for %r", field.label, exc_info=True)
        return False


def _fill_field(page, field, answer: str, *, family: str = "") -> bool:
    """Fill one resolved field; replay learned field_strategy when present."""
    from applypilot.apply.direct import field_strategy_fill
    from applypilot.apply.direct.playbook import lookup_field_strategy

    if field.options and field.tag != "select" and not field.combobox:
        ok = field_strategy_fill.fill_field_with_strategy(
            page, field, answer, family=family,
        )
        if ok:
            field_strategy_fill.record_fill_outcome(field, family, "click_label", True)
        return ok
    cached = lookup_field_strategy(field_strategy_fill.field_sig(field), family)
    if cached:
        ok = field_strategy_fill.fill_field_with_strategy(
            page, field, answer, family=family,
        )
        field_strategy_fill.record_fill_outcome(field, family, cached, ok)
        return ok
    ok = _fill_field_legacy(page, field, answer, family=family)
    if ok:
        method = field_strategy_fill.infer_fill_method(
            field,
            family,
            succeeded=True,
            used_click_label=field.type in {"checkbox", "radio"},
        )
        field_strategy_fill.record_fill_outcome(field, family, method, True)
    return ok


def _resolve_checkbox_group_pick(
    members,
    *,
    tokens: dict,
    job: dict | None = None,
    gemini_enabled: bool = True,
) -> tuple[str | None, str]:
    labels = tuple(m.label for m in members)
    question = next((m.section_header for m in members if m.section_header), "")
    qnorm = question.strip().lower()
    if "us time zone" in qnorm or "us time zones" in qnorm:
        pick = profile_binding.choose_select_option("Yes", labels)
        if pick:
            return pick, "group"
    if "sponsor" in qnorm or "h-1b" in qnorm or "visa status" in qnorm:
        if "us only" in qnorm or "posted in the us" in qnorm:
            pick = profile_binding.choose_select_option("Not applicable", labels)
            if pick:
                return pick, "group"
        pick = profile_binding.choose_select_option(
            str(tokens.get("require_sponsorship") or "No"), labels
        )
        if pick:
            return pick, "group"
    pick = profile_binding.choose_checkbox_group_option(question, labels)
    if pick:
        return pick, "group"
    if not gemini_enabled or not labels:
        return None, ""
    synthetic = profile_binding.Field(
        label=question or "Select the best option",
        type="checkbox",
        tag="input",
        name_attr=members[0].name_attr if members else "",
        section_header=question,
        required=True,
        options=labels,
        key=f"checkbox_group|{members[0].name_attr if members else question}",
    )
    outcome = resolver.resolve([synthetic], tokens, job=job, gemini_enabled=True)
    answer = outcome.answers.get(synthetic.key)
    if answer and answer in labels:
        return answer, outcome.via.get(synthetic.key, "t2:gemini")
    return None, ""


def _fill_checkbox_group(
    page,
    members,
    *,
    tokens: dict,
    job: dict | None = None,
    gemini_enabled: bool = True,
) -> tuple[str, str | None, str]:
    """Check exactly ONE option in a required checkbox group (e.g. 'how did you
    hear about us'). Returns (status, picked_label) with status in
    {'filled', 'unresolved'}; 'unresolved' means we won't guess (escalate)."""
    question = next((m.section_header for m in members if m.section_header), "")
    pick, via = _resolve_checkbox_group_pick(
        members, tokens=tokens, job=job, gemini_enabled=gemini_enabled
    )
    if not pick:
        return "unresolved", None, ""
    target = next((m for m in members if m.label == pick), None)
    if target is None:
        return "unresolved", None, ""
    try:
        loc = _locator(page, target)
        if loc.count() == 0:
            return "unresolved", None, ""
        loc.scroll_into_view_if_needed(timeout=3_000)
        loc.check(timeout=4_000)
        return "filled", pick, via
    except Exception:  # noqa: BLE001
        logger.debug("checkbox group fill failed for %r", question, exc_info=True)
        return "unresolved", None, ""


def _fill_technology_checkbox_group(
    page,
    members,
    *,
    tokens: dict,
    job: dict | None = None,
    gemini_enabled: bool = True,
) -> tuple[str, str | None, str]:
    """Check multiple technology options for 'select all that apply' groups."""
    from applypilot.apply.direct import profile_binding

    question = next((m.section_header for m in members if m.section_header), "")
    labels = tuple(m.label for m in members)
    picks = profile_binding.technology_checkbox_picks(labels)
    if not picks:
        return "unresolved", None, ""
    checked = 0
    picked: list[str] = []
    for pick in picks:
        target = next((m for m in members if m.label == pick), None)
        if target is None:
            continue
        clicked = False
        try:
            loc = _locator(page, target)
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=3_000)
                try:
                    if not loc.is_checked():
                        loc.check(timeout=4_000)
                    clicked = loc.is_checked()
                except Exception:  # noqa: BLE001
                    clicked = False
        except Exception:  # noqa: BLE001
            clicked = False
        if not clicked and target is not None:
            clicked = _check_checkbox_dom(page, target)
        if not clicked:
            clicked = _click_lever_section_checkbox(page, question, pick)
        if not clicked and target is not None:
            clicked = _click_option_near_label(page, target, pick)
        if clicked:
            checked += 1
            picked.append(pick)
        else:
            logger.debug(
                "technology checkbox fill failed for %r / %r",
                question,
                pick,
            )
    if not checked:
        return "unresolved", None, ""
    summary = ", ".join(picked[:6])
    if len(picked) > 6:
        summary += f" (+{len(picked) - 6} more)"
    return "filled", summary, "technology-group"


def _resolve_radio_group_pick(
    members,
    *,
    tokens: dict,
    job: dict | None = None,
    gemini_enabled: bool = True,
) -> tuple[str | None, str]:
    labels = tuple(m.label for m in members)
    lower = {str(label).strip().lower() for label in labels}
    if {"onsite", "remote", "hybrid"} & lower:
        for preferred in ("Remote", "Hybrid", "NA"):
            pick = profile_binding.choose_select_option(preferred, labels)
            if pick:
                return pick, "group"
    question = next((m.section_header for m in members if m.section_header), "")
    combined_label = f"{question} {' | '.join(labels)}".strip() or (labels[0] if labels else "")
    synthetic = profile_binding.Field(
        label=combined_label,
        type="radio",
        tag="input",
        name_attr=members[0].name_attr if members else "",
        section_header=question,
        required=True,
        options=labels,
        key=f"radio_group|{members[0].name_attr if members else question}",
    )
    tier0 = profile_binding.resolve_field(synthetic, tokens)
    if tier0:
        pick = profile_binding.choose_select_option(tier0.answer, labels)
        if pick:
            return pick, tier0.via or "label"
    if not gemini_enabled or not labels:
        return None, ""
    outcome = resolver.resolve([synthetic], tokens, job=job, gemini_enabled=True)
    answer = outcome.answers.get(synthetic.key)
    if answer and answer in labels:
        return answer, outcome.via.get(synthetic.key, "t2:gemini")
    return None, ""


def _fill_radio_group(
    page,
    members,
    *,
    tokens: dict,
    job: dict | None = None,
    gemini_enabled: bool = True,
) -> tuple[str, str | None, str]:
    from applypilot.apply.direct import profile_binding

    pick, via = _resolve_radio_group_pick(
        members, tokens=tokens, job=job, gemini_enabled=gemini_enabled
    )
    if not pick:
        return "unresolved", None, ""
    target = next((m for m in members if m.label == pick), None)
    if target is None:
        return "unresolved", None, ""
    name_attr = members[0].name_attr if members else ""
    try:
        loc = _locator(page, target)
        if loc.count() == 0:
            if not _click_radio_group_option(page, members, pick):
                return "unresolved", None, ""
        else:
            loc.scroll_into_view_if_needed(timeout=3_000)
            try:
                loc.check(timeout=4_000)
            except Exception:  # noqa: BLE001
                if not _click_radio_group_option(page, members, pick):
                    section = (members[0].section_header or "").strip()
                    hint = section if target.label.strip().lower() in {"yes", "no", "n/a"} else target.label
                    if not _click_option_near_label(page, profile_binding.Field(label=hint), pick):
                        return "unresolved", None, ""
        if name_attr and not _radio_group_is_checked(page, name_attr):
            if not _click_radio_group_option(page, members, pick):
                return "unresolved", None, ""
        return "filled", pick, via
    except Exception:  # noqa: BLE001
        logger.debug("radio group fill failed for %r", pick, exc_info=True)
        return "unresolved", None, ""


def _file_input_locator(page, field):
    """Locate a file <input> by its STABLE id/name first.

    Modern Greenhouse labels both the resume and cover-letter inputs "Attach"
    and React wipes the data-ap-key stamp once other fields are filled — so the
    ordinal restamp can land on the wrong input. The id/name (`resume`,
    `cover_letter`) survives re-render and uniquely identifies each input.
    """
    na = (field.name_attr or "").strip()
    if na:
        sel = f'input[type="file"][name="{na}"], input[type="file"][id="{na}"]'
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except Exception:  # noqa: BLE001
            pass
    return _locator(page, field)


def _is_ashby_autofill_file(field) -> bool:
    hint = f"{field.label} {field.name_attr} {field.section_header}".lower()
    return "autofill from resume" in hint or "autofill from résumé" in hint


def _upload_ashby_required_resume_input(page, resume_pdf: str) -> bool:
    """Upload to Ashby's required system resume input, not the optional autofill input."""
    selector = (
        'input[type="file"][id="_systemfield_resume"], '
        'input[type="file"][name="_systemfield_resume"]'
    )
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return False
        loc.set_input_files(resume_pdf, timeout=8_000)
        _wait_upload_complete(page)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("Ashby required resume input upload failed", exc_info=True)
        return False


def _upload_ashby_resume(page, resume_pdf: str) -> bool:
    """Ashby renders upload controls as buttons that open a file chooser."""
    if _upload_ashby_required_resume_input(page, resume_pdf):
        return True
    for label in ("Upload File", "Upload file"):
        try:
            button = page.get_by_role("button", name=label, exact=False).last
            if button.count() == 0:
                continue
            button.scroll_into_view_if_needed(timeout=3_000)
            with page.expect_file_chooser(timeout=8_000) as chooser_info:
                button.click(timeout=4_000)
            chooser_info.value.set_files(resume_pdf)
            _wait_upload_complete(page)
            return True
        except Exception:  # noqa: BLE001
            logger.debug("Ashby resume upload failed via %r", label, exc_info=True)
            continue
    return False


def _field_uploaded_name(page, field) -> str:
    try:
        loc = _file_input_locator(page, field)
        if loc.count() == 0:
            return ""
        return str(
            loc.evaluate(
                "el => (el.files && el.files[0] && el.files[0].name) || ''"
            )
            or ""
        )
    except Exception:  # noqa: BLE001
        return ""


def _file_accept_map(page) -> dict[str, str]:
    try:
        raw = page.evaluate(
            """() => {
              const m = {};
              document.querySelectorAll('input[type=file]').forEach((el) => {
                const k = el.name || el.id || '';
                if (k) m[k] = el.accept || '';
              });
              return m;
            }"""
        )
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _fill_cover_prose_fallback(
    page,
    *,
    cover_text: str,
    filled_rows: list[dict],
    family: str,
) -> None:
    """When no cover-letter file slot exists, paste cover text into prose fields."""
    text = str(cover_text or "").strip()
    if not text:
        return
    form = extractor.extract_fields(page)
    accept_map = _file_accept_map(page)
    has_cover_file = any(
        _is_cover_file_upload(
            {
                "label": f.label,
                "name": f.name_attr,
                "accept": accept_map.get(f.name_attr or "", ""),
                "required": f.required,
            },
            family=family,
        )
        for f in form.fields
        if f.type == "file"
    )
    if has_cover_file:
        return
    markers = (
        "cover letter",
        "coverletter",
        "motivation",
        "letter of interest",
        "why do you want",
        "why are you interested",
        "additional information",
        "anything else",
    )
    for f in form.fillable():
        if f.empty is False or f.type == "file":
            continue
        blob = f"{f.section_header} {f.label}".lower()
        if not any(m in blob for m in markers):
            continue
        if f.tag != "textarea" and f.type not in {"", "text"}:
            continue
        snippet = text[:4000]
        if _fill_field(page, f, snippet, family=family):
            filled_rows.append(
                _record_row(f.label, snippet[:200], ftype=f.type or f.tag, via="cover_prose")
            )
            _sleep_fill()
            return


def _fill_optional_gaps(
    page,
    *,
    tokens: dict,
    job: dict,
    gemini_enabled: bool,
    filled_rows: list[dict],
    outcome,
    family: str,
) -> None:
    """Fill optional controls still empty after the required path."""
    from applypilot.apply.direct import profile_binding

    form = extractor.extract_fields(page)
    filled_labels = {_normalize_audit_label(r.get("label", "")) for r in filled_rows}

    optional_combos = [
        f for f in form.fillable()
        if f.combobox and not f.required and f.empty
    ]
    for f in optional_combos:
        status, sub = _fill_combobox(
            page, f, tokens, gemini_enabled=gemini_enabled, family=family,
        )
        if sub is not None and outcome is not None:
            outcome.tier_max = max(outcome.tier_max, sub.tier_max)
            outcome.llm_field_count += sub.llm_field_count
        if status == "filled" and sub is not None:
            filled_rows.append(
                _record_row(
                    f.label,
                    sub.answers.get(f.key, ""),
                    ftype="select",
                    via=sub.via.get(f.key, ""),
                )
            )

    form = extractor.extract_fields(page)
    gaps = [
        f for f in form.fillable()
        if not f.required
        and f.empty
        and f.type not in {"file", "hidden", "submit", "button"}
        and not f.combobox
        and _normalize_audit_label(f.label) not in filled_labels
        and not profile_binding.is_phantom_technology_select(f)
    ]
    if not gaps:
        return

    sub = resolver.resolve(gaps, tokens, job=job, gemini_enabled=gemini_enabled)
    if outcome is not None:
        outcome.tier_max = max(outcome.tier_max, sub.tier_max)
        outcome.llm_field_count += sub.llm_field_count
    for f in gaps:
        ans = sub.answers.get(f.key)
        if not ans:
            continue
        if _fill_field(page, f, ans, family=family):
            filled_rows.append(
                _record_row(
                    f.label, ans, ftype=f.type or f.tag, via=sub.via.get(f.key, ""),
                )
            )
            _sleep_fill()


def _upload_files(
    page,
    form,
    resume_pdf: str,
    cover_pdf: str | None,
    *,
    family: str = "",
) -> None:
    uploaded_resume = False
    if family == "ashby":
        uploaded_resume = _upload_ashby_required_resume_input(page, resume_pdf)

    file_fields = [f for f in form.fields if f.type == "file"]
    cover_fields: list = []
    resume_fields: list = []
    accept_map = _file_accept_map(page)

    for f in file_fields:
        if family == "ashby" and _is_ashby_autofill_file(f):
            continue
        hint = f"{f.label} {f.name_attr} {f.section_header}".lower()
        accept = accept_map.get(f.name_attr or "", "")
        if _file_hint_is_photo(hint) or _upload_accepts_images_only(accept):
            continue
        pseudo = {
            "label": f.label,
            "name": f.name_attr,
            "accept": accept,
            "required": f.required,
        }
        if _is_resume_file_upload(pseudo, family=family):
            resume_fields.append(f)
        elif _is_cover_file_upload(pseudo, family=family):
            cover_fields.append(f)
        elif family == "lever":
            resume_fields.append(f)

    cover_path = cover_pdf if cover_pdf and Path(cover_pdf).exists() else None

    for f in resume_fields:
        existing = _field_uploaded_name(page, f)
        if existing and resume_pdf and Path(resume_pdf).name.lower() in existing.lower():
            uploaded_resume = True
            continue
        try:
            _file_input_locator(page, f).set_input_files(resume_pdf, timeout=8_000)
            uploaded_resume = True
            _wait_upload_complete(page)
        except Exception:  # noqa: BLE001
            logger.debug("resume upload failed for %r", f.label, exc_info=True)

    for f in cover_fields:
        if not cover_path:
            continue
        existing = _field_uploaded_name(page, f) or ""
        if resume_pdf and Path(resume_pdf).name.lower() in existing.lower():
            continue
        try:
            _file_input_locator(page, f).set_input_files(cover_path, timeout=8_000)
            _wait_upload_complete(page)
        except Exception:  # noqa: BLE001
            logger.debug("cover upload failed for %r", f.label, exc_info=True)

    if not uploaded_resume and family == "ashby":
        _upload_ashby_resume(page, resume_pdf)


_ASHBY_REQUIRED_VISIBLE_CONTROLS: tuple[tuple[str, str], ...] = (
    (
        "Are you legally authorized to work in the country where this role is located, for any employer?",
        "Yes",
    ),
    (
        "Will you now or will you in the future require employment visa sponsorship?",
        "require_sponsorship",
    ),
    (
        "Will you now or in the future require Notion to sponsor an immigration case in order to employ you?",
        "require_sponsorship",
    ),
    (
        "Are you excited and able to join us in person on those days?",
        "Yes",
    ),
    (
        "We work from our offices on Mondays, Tuesdays, and Thursdays (Anchor Days). If you need an accommodation, we’ll partner with you and explore reasonable options consistent with applicable law. Are you able to commit to working from one of our offices on Anchor Days each week?",
        "Yes",
    ),
)


def _fill_ashby_required_visible_controls(page, tokens: dict) -> list[tuple[str, str]]:
    filled: list[tuple[str, str]] = []
    for label, answer_or_token in _ASHBY_REQUIRED_VISIBLE_CONTROLS:
        answer = tokens.get(answer_or_token, "") if answer_or_token in tokens else answer_or_token
        if not str(answer or "").strip():
            continue
        field = profile_binding.Field(label=label)
        if _click_option_near_label(page, field, str(answer)):
            filled.append((label, str(answer)))
            page.wait_for_timeout(250)
    return filled


def _wait_upload_complete(page) -> None:
    """Give the async file upload (e.g. Greenhouse -> S3) time to settle.

    The filename chip appears instantly but the bytes upload in the background;
    submitting before it finishes makes the ATS reject 'Resume is required'.
    A small PDF takes a couple of seconds; wait conservatively.
    """
    page.wait_for_timeout(4_000)


_VERIFY_MARKERS = (
    "enter the 8-character code",
    "code to confirm you're a human",
    "a verification code was sent",
    "the verification code was sent",
    "verification code was sent to this email",
    "enter the code we sent",
    "confirm your identity",
    "one-time pass code",
)


def _verification_wall_present(body: str) -> bool:
    return _matches_any(body, _VERIFY_MARKERS)


def _locate_code_input(page):
    for hint in ("security code", "verification code", "confirm you're a human"):
        loc = page.get_by_label(hint, exact=False).first
        if loc.count() > 0:
            return loc
    loc = page.locator(
        'input[maxlength="8"], input[maxlength="6"], input[autocomplete="one-time-code"]'
    ).first
    if loc.count() > 0:
        return loc
    return None


def _code_digit_fields(page) -> list:
    try:
        form = extractor.extract_fields(page)
    except Exception:  # noqa: BLE001
        return []
    fields = []
    for field in form.fields:
        blob = f"{field.label} {field.name_attr} {field.autocomplete}".lower()
        if (
            field.tag == "input"
            and field.type in {"number", "text", "tel"}
            and (
                "verification code" in blob
                or "security code" in blob
                or "one-time" in blob
            )
        ):
            fields.append(field)
    return sorted(fields, key=lambda f: f.ap_id)


def _fill_verification_code(page, code: str, code_input) -> bool:
    digit_fields = _code_digit_fields(page)
    if len(digit_fields) >= 4:
        for ch, field in zip(code, digit_fields):
            loc = _locator(page, field)
            if loc.count() == 0:
                return False
            loc.fill(ch, timeout=5_000)
            page.wait_for_timeout(100)
        return True
    if code_input is None or code_input.count() == 0:
        return False
    code_input.fill(code, timeout=5_000)
    return True


def _click_verification_continue(page) -> bool:
    for text in ("verify", "continue", "next", "confirm"):
        if unblock._click_text(page, text):
            return True
    return False


def _verification_company_hint(job: dict) -> str:
    company = str(job.get("company") or job.get("site") or "").strip()
    if company.lower() in {"", "linkedin", "linkedin->company", "unknown"}:
        return ""
    return company


def _try_clear_verification_wall(
    page,
    job: dict,
    *,
    adapter: Adapter,
    worker_id: int,
) -> tuple[bool, str | None]:
    """Return (ok, escalate_reason). ok=False means caller should return failed:direct_needs_verification."""
    if not apply_settings.email_verification_enabled():
        return False, "email_verification_code"

    body = _body_text_lower(page)
    if not _verification_wall_present(body):
        return True, None

    company = _verification_company_hint(job)
    since = time.time() - 120.0
    code_input = _locate_code_input(page)

    if code_input is None or code_input.count() == 0:
        _click_submit(page, adapter)
        page.wait_for_timeout(2_000)
        code_input = _locate_code_input(page)

    digit_fields = _code_digit_fields(page)
    code_len = len(digit_fields) if len(digit_fields) >= 4 else 8
    if code_input is not None and code_input.count() > 0:
        try:
            ml = code_input.get_attribute("maxlength", timeout=2_000)
            code_len = email_verify.infer_code_length(
                label=body[:500], maxlength=ml
            )
        except Exception:  # noqa: BLE001
            pass

    code = email_verify.fetch_verification_code(
        company_hint=company,
        since_epoch_s=since,
        code_length=code_len,
    )
    if not code:
        logger.info("[W%d] Verification code not received in time", worker_id)
        return False, "email_verification_code"

    if (code_input is None or code_input.count() == 0) and not digit_fields:
        return False, "email_verification_code"

    try:
        if not _fill_verification_code(page, code, code_input):
            return False, "email_verification_code"
        page.wait_for_timeout(400)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to fill verification code", exc_info=True)
        return False, "email_verification_code"

    if not direct_captcha.solve_captcha_if_present(page):
        logger.info("[W%d] Captcha present but not solved", worker_id)
        return False, "captcha_unsolved"

    _click_verification_continue(page)
    page.wait_for_timeout(1_800)
    return True, None


def _click_workday_submit(page) -> bool:
    """Workday final submit uses data-automation-id, not always type=submit."""
    selectors = (
        '[data-automation-id="submitButton"]',
        '[data-automation-id="SubmitButton"]',
        '[data-automation-id="bottom-navigation-next-button"]',
    )
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            btn = loc.first
            btn_text = (btn.inner_text(timeout=2_000) or "").strip().lower()
            if sel.endswith("next-button") and "submit" not in btn_text:
                continue
            btn.scroll_into_view_if_needed(timeout=3_000)
            btn.click(timeout=8_000)
            return True
        except Exception:  # noqa: BLE001
            continue
    try:
        clicked = page.evaluate(
            """() => {
              const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const vis = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              };
              const tryClick = (el) => {
                if (!vis(el)) return false;
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
                el.click();
                return true;
              };
              for (const sel of [
                '[data-automation-id="submitButton"]',
                '[data-automation-id="bottom-navigation-next-button"]',
              ]) {
                for (const el of document.querySelectorAll(sel)) {
                  const t = norm(el.innerText || el.value || el.getAttribute('aria-label'));
                  if (sel.includes('submitButton') || t.includes('submit')) {
                    if (tryClick(el)) return true;
                  }
                }
              }
              for (const el of document.querySelectorAll('button, [role="button"], input[type="submit"]')) {
                const t = norm(el.innerText || el.value || el.getAttribute('aria-label'));
                if (t === 'submit' || t.startsWith('submit ') || t === 'submit application') {
                  if (tryClick(el)) return true;
                }
              }
              return false;
            }"""
        )
        if clicked:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _fill_workday_fieldset_radios(
    page,
    *,
    tokens: dict,
    filled_rows: list,
) -> None:
    """Fill Workday EEO/voluntary radiogroups located by fieldset legend."""
    try:
        groups = page.evaluate(
            """() => {
              const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              const vis = (el) => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              };
              const out = [];
              for (const fs of document.querySelectorAll('fieldset')) {
                const lg = fs.querySelector('legend');
                if (!lg || !vis(fs)) continue;
                const legend = norm(lg.innerText);
                if (!legend) continue;
                if (fs.querySelector('input[type="radio"]:checked, [role="radio"][aria-checked="true"]')) {
                  continue;
                }
                const options = [];
                for (const r of fs.querySelectorAll('input[type="radio"], [role="radio"]')) {
                  if (!vis(r)) continue;
                  const label = norm(
                    (r.labels && r.labels[0] && r.labels[0].innerText) ||
                    r.getAttribute('aria-label') ||
                    r.value ||
                    ''
                  );
                  if (label) options.push(label);
                }
                if (options.length) out.push({ legend, options });
              }
              return out;
            }"""
        )
    except Exception:  # noqa: BLE001
        return
    if not groups:
        return
    from applypilot.apply.direct import profile_binding

    for group in groups:
        legend = str(group.get("legend") or "")
        options = tuple(str(o) for o in (group.get("options") or []) if o)
        if not legend or not options:
            continue
        pseudo = profile_binding.Field(
            label=legend,
            type="radio",
            tag="input",
            section_header=legend,
            required=False,
            options=options,
        )
        res = profile_binding.resolve_field(pseudo, tokens)
        pick = None
        via = ""
        if res:
            pick = profile_binding.choose_select_option(res.answer, options)
            via = res.via or "label"
        if not pick:
            pick = profile_binding.choose_select_option("Decline to answer", options)
            via = via or "decline"
        if not pick:
            continue
        try:
            page.evaluate(
                """({ legend, pick }) => {
                  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                  const want = norm(pick);
                  for (const fs of document.querySelectorAll('fieldset')) {
                    const lg = fs.querySelector('legend');
                    if (!lg || norm(lg.innerText) !== norm(legend)) continue;
                    for (const r of fs.querySelectorAll('input[type="radio"], [role="radio"]')) {
                      const label = norm(
                        (r.labels && r.labels[0] && r.labels[0].innerText) ||
                        r.getAttribute('aria-label') ||
                        r.value ||
                        ''
                      );
                      if (label === want || label.includes(want) || want.includes(label)) {
                        r.click();
                        return true;
                      }
                    }
                  }
                  return false;
                }""",
                {"legend": legend, "pick": pick},
            )
            filled_rows.append(
                _record_row(legend, pick, ftype="radio", via=via or "workday:fieldset")
            )
        except Exception:  # noqa: BLE001
            continue


def _click_submit(page, adapter: Adapter) -> bool:
    if adapter.family == "workday":
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(400)
        if _click_workday_submit(page):
            return True
    # 1) Text-matched submit control (button / link / input / any element whose
    #    normalized text equals a submit label). unblock._click_text handles
    #    scroll-into-view, overlay-intercept (force), and styled buttons.
    for text in adapter.submit_button_texts:
        try:
            inp = page.locator(f'input[type="submit"][value*="{text}" i]').first
            if inp.count() > 0:
                inp.scroll_into_view_if_needed(timeout=3_000)
                inp.click(timeout=8_000)
                return True
        except Exception:  # noqa: BLE001
            pass
        if unblock._click_text(page, text):
            return True
    # 2) Fallback: a real submit control exists but its text didn't match our
    #    list (custom label). We only reach here AFTER the identity guard
    #    confirmed this is a genuine application form, so the lone submit on the
    #    page is the application submit. Prefer an unambiguous single candidate.
    for sel in ('button[type="submit"]', 'input[type="submit"]'):
        try:
            loc = page.locator(sel)
            if loc.count() == 1:
                cand = loc.first
                cand.scroll_into_view_if_needed(timeout=3_000)
                cand.click(timeout=8_000)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


# Multi-step forms advance with one of these controls. They are NOT a final
# submit (clicking one does not send the application — it only reveals the next
# page), so it is safe to click them even during a dry run.
_ADVANCE_BUTTON_TEXTS: tuple[str, ...] = (
    "next", "continue", "save and continue", "save & continue", "next step",
    "next: ", "proceed", "review", "save and next", "continue to",
)
# Words that mean an irreversible side-effect, never auto-clicked as "advance".
_ADVANCE_DENY = ("submit", "apply", "create account", "register", "sign up", "pay")


def _multistep_max_pages() -> int:
    try:
        return max(1, int(os.environ.get("APPLYPILOT_DIRECT_MAX_PAGES", "6")))
    except ValueError:
        return 6


def _is_review_only_multistep_page(fields) -> bool:
    """True when a post-Next step is a final review/submit screen, not questions.

    Micro1 and similar portals use optional number/text screening on later steps.
    Treat those as fillable pages even when no identity field is marked required.
    """
    from applypilot.apply.direct import unblock

    if len(fields) < 2:
        return True
    if unblock.has_identity_field(fields) or any(f.required for f in fields):
        return False
    substantive = [
        f
        for f in fields
        if f.type != "file"
        and f.type not in {"hidden", "submit", "button"}
        and str(f.label or "").strip()
    ]
    return len(substantive) == 0


def _find_advance_button(page, *, family: str = ""):
    """Return a clickable 'Next/Continue' control for a multi-step form, or None.

    Only matches pure-navigation controls (never a final Submit/Apply or an
    account-creation button), so advancing has no irreversible side-effect.
    """
    try:
        cands = page.evaluate(unblock._CLICKABLES_JS)
    except Exception:  # noqa: BLE001
        return None
    deny = _ADVANCE_DENY
    advance_texts = _ADVANCE_BUTTON_TEXTS
    if family == "workday":
        # Workday starts with a required account-creation step before the actual
        # application pages. This is not the final application submit.
        deny = tuple(d for d in _ADVANCE_DENY if d not in {"create account"})
        advance_texts = (*_ADVANCE_BUTTON_TEXTS, "create account")
    for text in cands:
        low = text.strip().lower()
        if family == "workday" and low == "create account":
            return text
        if not low or any(d in low for d in deny):
            continue
        if any(low == t or low.startswith(t) for t in advance_texts):
            return text
    return None


# Options live only inside the OPEN menu. Scope to it — reading bare
# `.select__option` leaks options from a different react-select (e.g. the
# Country picker) that happens to be mounted, which snaps answers to the wrong
# widget.
# Strictly the open react-select menu. A bare `[role=option]` also matches the
# phone-number country picker's 246-item listbox, which would snap answers to a
# country; `.select__menu` is the only safe anchor.
_OPTION_SELECTOR_GREENHOUSE = (
    '.select__menu .select__option, .select__menu [role="option"]'
)
_OPTION_SELECTOR_ASHBY = '[role="listbox"] [role="option"], [data-headlessui-state] [role="option"]'
_OPTION_SELECTOR_LEVER = (
    '.select__menu .select__option, .select__menu [role="option"], '
    '[role="listbox"] [role="option"]'
)
_OPTION_SELECTOR = _OPTION_SELECTOR_GREENHOUSE


def _option_selector(family: str) -> str:
    if family == "ashby":
        return _OPTION_SELECTOR_ASHBY
    if family in {"lever", "workable"}:
        return _OPTION_SELECTOR_LEVER
    return _OPTION_SELECTOR_GREENHOUSE


def _read_open_options(page, *, family: str = "greenhouse") -> tuple[str, ...]:
    """Read option labels of the currently-open dropdown menu."""
    sel = _option_selector(family)
    try:
        opts = page.eval_on_selector_all(
            sel,
            "els => els.map(e => (e.innerText || '').trim()).filter(Boolean)",
        )
        return tuple(dict.fromkeys(opts))  # de-dupe, preserve order
    except Exception:  # noqa: BLE001
        return ()


# JS: tag the .select__control whose combobox's accessible label matches `label`.
# Locating fresh by label (not the stamped data-ap-key) survives React
# re-renders that wipe the stamp, which is what made some widgets fail to open.
#
# Scoring picks the MOST SPECIFIC combobox instead of the first loose hit. The
# old `want.includes(txt)` let a short generic label ("Country") match any
# longer question that merely contained that word — e.g. "...authorized to work
# in the country..." opened the Country picker, read its 244 country options,
# and snapped the answer to "Norfolk Island +672". The weak (question-contains-
# label) branch now requires a label of real length (>= 12 chars).
_MARK_COMBO_JS = r"""(label) => {
  const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const want = norm(label).slice(0, 60);
  document.querySelectorAll('[data-ap-open]').forEach(e => e.removeAttribute('data-ap-open'));
  const inps = [...document.querySelectorAll('.select__input[role=combobox]')];
  let best = null, bestScore = 0;
  for (const inp of inps) {
    const lid = inp.getAttribute('aria-labelledby');
    const t = lid ? document.getElementById(lid) : null;
    const txt = norm(t ? t.innerText : (inp.getAttribute('aria-label') || '')).slice(0, 60);
    if (!txt) continue;
    let score = 0;
    if (txt === want) score = 1000;
    else if (txt.includes(want)) score = want.length;
    else if (want.startsWith(txt) || txt.startsWith(want)) score = Math.min(txt.length, want.length);
    else if (want.includes(txt) && txt.length >= 12) score = txt.length;
    if (score > bestScore) { bestScore = score; best = inp; }
  }
  if (best && bestScore > 0) {
    const ctrl = best.closest('.select__control') || best.parentElement;
    if (ctrl) { ctrl.setAttribute('data-ap-open', '1'); return true; }
  }
  return false;
}"""


_MARK_ASHBY_COMBO_JS = r"""(label) => {
  const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const want = norm(label).slice(0, 80);
  document.querySelectorAll('[data-ap-open]').forEach(e => e.removeAttribute('data-ap-open'));
  if (!want) return false;
  const texts = [...document.querySelectorAll('label, [class*="label"], [class*="Label"], [class*="field"], [class*="Field"]')];
  for (const el of texts) {
    const txt = norm(el.innerText || el.textContent || '').slice(0, 120);
    if (!txt || !(txt === want || txt.includes(want) || want.includes(txt))) continue;
    let root = el;
    for (let i = 0; i < 6 && root; i++, root = root.parentElement) {
      const combo = root.querySelector('input[role="combobox"], [role="combobox"]');
      if (combo) { combo.setAttribute('data-ap-open', '1'); return true; }
    }
  }
  return false;
}"""


def _split_multi_answer(answer: str) -> list[str]:
    import re as _re

    parts = _re.split(r"[,;/]|\band\b", answer, flags=_re.I)
    return [p.strip() for p in parts if p.strip()]


def _fill_combobox(
    page,
    field,
    tokens,
    *,
    gemini_enabled: bool,
    family: str = "greenhouse",
) -> tuple[str, object]:
    """Open a react-select widget, resolve against its LIVE options, click one.

    Options only exist in the DOM once the control is opened, so resolution has
    to happen here (not in the upfront batch). Returns (status, sub_outcome)
    with status in {'filled', 'unresolved', 'error'}.
    """
    from dataclasses import replace

    def _escape():
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass

    opt_sel = _option_selector(family)

    try:
        _escape()  # close any stray open menu so we read the right one
        page.wait_for_timeout(150)
        opener = None
        if family == "greenhouse":
            if not page.evaluate(_MARK_COMBO_JS, field.label):
                return "error", None
            opener = page.locator('[data-ap-open="1"]').first
        elif family == "ashby":
            if page.evaluate(_MARK_ASHBY_COMBO_JS, field.label):
                opener = page.locator('[data-ap-open="1"]').first
            elif "location" in field.label.lower():
                opener = page.locator(
                    'input[role="combobox"][placeholder*="Start typing"]'
                ).first
            else:
                opener = page.get_by_role("combobox", name=field.label, exact=False).first
                if opener.count() == 0:
                    opener = page.locator(f'[aria-label*="{field.label[:40]}"]').first
        else:
            opener = page.get_by_role("combobox", name=field.label, exact=False).first
            if opener.count() == 0:
                opener = page.locator(f'[aria-label*="{field.label[:40]}"]').first
        if opener is None or opener.count() == 0:
            return "error", None
        opener.scroll_into_view_if_needed(timeout=3_000)
        opener.click(timeout=4_000)
        page.wait_for_timeout(500)
        options = _read_open_options(page, family=family)
        if not options:
            try:
                opener.click(timeout=2_000)
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(500)
            except Exception:  # noqa: BLE001
                pass
            options = _read_open_options(page, family=family)
        if not options:
            typed = profile_binding.resolve_field(
                replace(field, tag="input", combobox=False), tokens
            )
            type_text = (typed.answer if typed else "") or ""
            if not type_text.strip():
                _escape()
                return "error", None
            try:
                opener.click(timeout=2_000)
                opener.press_sequentially(type_text[:80], delay=40, timeout=8_000)
                page.wait_for_timeout(900)
            except Exception:  # noqa: BLE001
                _escape()
                return "error", None
            options = _read_open_options(page, family=family)
        if not options:
            _escape()
            return "error", None
        rf = replace(field, options=options, tag="select", combobox=False)
        sub = resolver.resolve([rf], tokens, gemini_enabled=gemini_enabled)
        ans = sub.answers.get(rf.key)
        if not ans:
            _escape()
            return "unresolved", sub
        picks = _split_multi_answer(ans) if field.is_multi else [ans]
        clicked = 0
        for pick in picks:
            snapped = profile_binding.choose_select_option(pick, tuple(options)) or pick
            opt = page.locator(opt_sel).filter(has_text=snapped).first
            if opt.count() == 0:
                opt = page.get_by_role("option", name=snapped, exact=False).first
            if opt.count() == 0:
                continue
            opt.click(timeout=4_000)
            page.wait_for_timeout(250)
            clicked += 1
        if clicked == 0:
            _escape()
            return "unresolved", sub
        if not field.is_multi:
            _escape()
        page.wait_for_timeout(300)
        return "filled", sub
    except Exception:  # noqa: BLE001
        logger.debug("combobox fill failed for %r", field.label, exc_info=True)
        _escape()
        return "error", None


def apply_via_direct(
    job: dict,
    *,
    port: int,
    worker_id: int = 0,
    dry_run: bool = False,
    gemini_enabled: bool | None = None,
) -> DriverResult:
    """Run one deterministic apply against the worker's Chrome (CDP on `port`)."""
    start = time.monotonic()
    url = _job_url(job)
    family = fingerprint.ats_family(url)
    fp = fingerprint.provider_fingerprint(url)
    used_nav_sigs: list[str] = []

    def done(result: str, *, escalate=False, reason=None, outcome=None,
             fields_total=0) -> DriverResult:
        elapsed = int((time.monotonic() - start) * 1000)
        dr = DriverResult(
            result=result, elapsed_ms=elapsed, escalate=escalate,
            escalate_reason=reason, ats_family=family, fingerprint=fp,
            fields_total=fields_total,
        )
        if outcome is not None:
            dr.tier_resolved = outcome.tier_max
            dr.fields_llm = outcome.llm_field_count
        return dr

    adapter = get_adapter(family)
    # Custom career domains (dropbox.jobs, stripe.com/jobs, instacart.careers)
    # embed a Greenhouse form behind a URL the host/param fingerprint reads as
    # 'unknown'. For those, defer the verdict: navigate, then content-sniff the
    # loaded page (below) before escalating. A non-'unknown' adapter-less family
    # (e.g. workday) can't be rescued this way, so it still gives up now.
    can_content_sniff = (
        adapter is None and family == fingerprint.UNKNOWN_FAMILY and bool(url)
    )
    from applypilot.apply.direct import generic as generic_mod

    if adapter is None and not can_content_sniff:
        # No known adapter and not a sniffable custom-domain embed. Attempt the
        # form generically (extract→resolve→fill→verify is vendor-agnostic) so we
        # can apply on plain company forms / Indian ATS. Excluded families
        # (greenhouse/ashby) are never attempted here — the launcher parks them.
        excluded = apply_settings.skipped_ats_families()
        if family not in excluded and generic_mod.generic_form_enabled() and url:
            adapter = generic_mod.ADAPTER
        else:
            return done("failed:direct_no_adapter", escalate=True, reason="no_adapter")
    if not url:
        return done("failed:direct_no_url", escalate=True, reason="no_url")

    from applypilot.apply import visit_ledger

    skip_visit, visit_reason, _last_visit = visit_ledger.visit_should_skip(url)
    if skip_visit:
        return done(f"skipped:apply_visit:{visit_reason}")

    # Resume is required to fill/submit. Fail fast for a known adapter (skips a
    # browser launch); for the content-sniff path defer this until the page
    # confirms a supported ATS so an unsniffable page escalates as no_adapter.
    resume_pdf: str | None = None
    if adapter is not None:
        resume_pdf = _resume_pdf_path(job)
        if not resume_pdf:
            return done("failed:resume_pdf_missing")

    if gemini_enabled is None:
        gemini_enabled = apply_settings.direct_gemini_enabled()

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    page = None
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15_000)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        # Fresh tab per job: avoids inheriting a stale/half-filled page from a
        # prior attempt and bounds every implicit wait so one job can't hang the
        # worker (the in-process Driver isn't covered by the Claude subprocess
        # wall-timeout).
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)

        nav_url = _canonical_apply_url(url, family)
        try:
            page.goto(nav_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            return done("failed:direct_nav_timeout", escalate=True, reason="nav_timeout")
        if family in {"ashby", "workday"}:
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(2_500 if family == "workday" else 1_200)
        try:
            unblock._dismiss_cookies(page)
        except Exception:  # noqa: BLE001
            logger.debug("cookie dismiss failed", exc_info=True)

        # Login wall? Pause for a human to sign in rather than failing. The job is
        # parked awaiting_login (reversible); after you log in + Resume it retries.
        from applypilot.apply import login_gate
        from applypilot.apply.direct import login_detect

        try:
            has_pw = page.locator("input[type=password]").count() > 0
        except Exception:  # noqa: BLE001
            has_pw = False
        try:
            quick_fields = page.locator("input, textarea, select").count()
        except Exception:  # noqa: BLE001
            quick_fields = 0
        body_text = _body_text_lower(page)
        try:
            html_text = page.content()
        except Exception:  # noqa: BLE001
            html_text = ""
        if login_detect.detect_login_required(
            page.url,
            body_text=body_text,
            has_password_field=has_pw,
            application_field_count=quick_fields,
        ):
            dom = login_detect.login_domain(page.url) or login_detect.login_domain(url)
            has_google = login_detect.has_google_signin(body_text, html=html_text)
            login_reason = "login_required" if has_google else "login_required_no_google"
            login_gate.request_login(
                dom,
                url=url,
                reason=login_reason,
                has_google_signin=has_google,
            )
            logger.info(
                "[W%d] Direct login wall on %s — awaiting login (%s)",
                worker_id,
                dom,
                login_reason,
            )
            return done(f"awaiting_login:{dom}", reason=login_reason)

        if family == "workday":
            from applypilot.apply.direct.adapters import workday as wd_mod

            try:
                wd_html = page.content()
            except Exception:  # noqa: BLE001
                wd_html = html_text
            wd_state = wd_mod.detect_workday_state(wd_html)
            if (
                wd_mod.is_login_wall(wd_html)
                or wd_mod.is_unauthenticated_apply_gate(wd_html, page_url=page.url)
                or wd_state == "account_or_signin"
            ):
                dom = login_detect.login_domain(page.url) or login_detect.login_domain(url)
                has_google = login_detect.has_google_signin(body_text, html=wd_html)
                login_reason = "workday_sign_in"
                login_gate.request_login(
                    dom,
                    url=url,
                    reason=login_reason,
                    has_google_signin=has_google,
                )
                logger.info(
                    "[W%d] Workday sign-in wall on %s — awaiting login (%s)",
                    worker_id,
                    dom,
                    login_reason,
                )
                return done(f"awaiting_login:{dom}", reason=login_reason)

        # Content-based ATS detection: the URL fingerprint said 'unknown', so
        # sniff the loaded page for a known backing ATS (custom-domain Greenhouse
        # embeds). On a high-confidence marker, switch to that adapter + the
        # normal extraction path; otherwise escalate exactly as before.
        if adapter is None:
            sniffed_family, sniffed_form_url = _content_sniff_family(page)
            if get_adapter(sniffed_family) is None:
                # Two-step custom flows (dropbox.jobs detail page) only load the
                # ATS form after an Apply click; reveal once, then re-sniff.
                if _click_apply_to_reveal(page):
                    sniffed_family, sniffed_form_url = _content_sniff_family(page)
            sniffed_adapter = get_adapter(sniffed_family)
            if sniffed_adapter is None:
                # Not a recognized embed — attempt the form generically rather
                # than give up (parks on uncertainty, never junk-submits).
                if generic_mod.generic_form_enabled():
                    sniffed_family = generic_mod.GENERIC_FAMILY
                    sniffed_adapter = generic_mod.ADAPTER
                else:
                    return done(
                        "failed:direct_no_adapter", escalate=True, reason="no_adapter"
                    )
            family = sniffed_family
            # URL still reads 'unknown', so derive the fingerprint from the
            # content-detected family (not the URL) for correct outcome records.
            fp = f"{family}:url"
            adapter = sniffed_adapter
            logger.info(
                "[W%d] Direct content-sniff reclassified unknown -> %s: %s",
                worker_id, family, url[:80],
            )
            if sniffed_form_url and sniffed_form_url != page.url:
                try:
                    page.goto(
                        sniffed_form_url, wait_until="domcontentloaded",
                        timeout=_NAV_TIMEOUT_MS,
                    )
                except Exception:  # noqa: BLE001
                    return done(
                        "failed:direct_nav_timeout", escalate=True, reason="nav_timeout"
                    )
                page.wait_for_timeout(1_200)
            if resume_pdf is None:
                resume_pdf = _resume_pdf_path(job)
                if not resume_pdf:
                    return done("failed:resume_pdf_missing")

        body = _body_text_lower(page)
        if _matches_any(body, adapter.expired_markers):
            return done("expired")

        _reveal_form(page, adapter)
        _wait_for_form_ready(
            page,
            timeout_ms=15_000 if family == "workday" else 8_000,
        )
        form = extractor.extract_fields(page)
        fields = form.fillable()

        # Form-acquisition gate. The Driver can fill any form it can see, but it
        # cannot navigate: a job-board landing page, an off-page Apply link, a
        # cookie/login wall, or a slow JS mount all leave us without the real
        # application form. Detect that here — no form, a partial form, or a
        # 2+-field form with NO identity field (search box / newsletter) — and
        # hand the page to the Gemini unblock tier to surface the real form.
        # Only then fill. This also prevents filling/submitting the wrong form.
        needs_unblock = (
            form.partial
            or len(fields) < 2
            or not unblock.has_identity_field(fields)
        )
        if needs_unblock and unblock.unblock_enabled():
            block_reason = (
                "partial_form" if form.partial
                else "no_form" if len(fields) < 2
                else "no_application_form"
            )
            try:
                from applypilot.apply.direct import unblock_learning

                if unblock_learning.run_unblock_with_learning(
                    page,
                    job,
                    family=family,
                    worker_id=worker_id,
                    reason=block_reason,
                    used_state_sigs=used_nav_sigs,
                ):
                    _reveal_form(page, adapter)
                    form = extractor.extract_fields(page)
                    fields = form.fillable()
            except unblock_learning.EscalationCapHit as exc:
                return done(
                    "failed:direct_escalation_cap",
                    escalate=False,
                    reason=str(exc)[:120],
                )
            except unblock.GeminiQuotaExhausted as exc:
                # Gemini is capped — fall through to the normal escalate path so
                # the next tier (Claude, if allowed) or park-and-continue runs.
                return done(
                    "failed:direct_unblock_quota", escalate=True,
                    reason=f"gemini_quota:{block_reason}",
                )

        if form.partial:
            return done("failed:direct_partial_form", escalate=True, reason="partial_form")
        if len(fields) < 2:
            return done("failed:direct_no_form", escalate=True, reason="no_form")
        if not unblock.has_identity_field(fields):
            return done(
                "failed:direct_no_application_form", escalate=True,
                reason="no_application_form",
            )
        if unblock.looks_like_non_application_form(fields):
            return done(
                "failed:direct_no_application_form",
                escalate=False,
                reason="no_application_form",
            )

        tokens = _build_tokens(job, resume_pdf)

        # ---- Per-page fill loop (multi-step forms) ----------------------------
        # Many portals paginate: page 1 collects identity + resume with a
        # "Next"/"Continue" button, later pages add questions, then a final
        # Submit. We fill the current page, and if a pure-navigation advance
        # button is present (never a Submit/Apply/Create-account), click it and
        # repeat. Clicking Next has no irreversible side-effect, so the loop runs
        # in dry-run too (it just stops before the FINAL submit). filled_rows and
        # the resolver outcome accumulate across pages.
        from applypilot.apply.cover_resolve import resolve_apply_cover_letter

        filled_rows: list[dict] = []
        outcome = None
        unresolved_state: dict[str, int] = {"count": 0}
        cover_upload: str | None = None
        cover_resolved = False
        _cl_text = ""
        max_pages = _multistep_max_pages()

        def _form_record(extra_errors=None) -> dict:
            return {
                "form_url": url,
                "page_title": (job.get("title") or "")[:160],
                "company": job.get("site") or "",
                "fields": filled_rows,
                "fill_actions": [],
                "visible_errors": list(extra_errors or []),
                "empty_required": unresolved_state["count"],
                "field_count": len(filled_rows),
                "engine": "direct",
            }

        for page_num in range(max_pages):
            if page_num > 0:
                # New page after clicking Next: wait for the next step's form to
                # mount (SPA pages render after navigation) before reading it, so
                # a slow page is not mistaken for a confirmation page.
                _wait_for_form_ready(page)
                form = extractor.extract_fields(page)
                fields = form.fillable()
                if _is_review_only_multistep_page(fields):
                    # Confirmation/review page (just a Submit, or only optional
                    # chrome) — finalize and submit.
                    break

            # Three field classes, each handled differently:
            #   - file       -> _upload_files (never the answer resolver)
            #   - combobox   -> opened individually, resolved against live options
            #   - regular    -> one upfront batch resolve + fill
            combos = [f for f in fields if f.combobox]
            non_combo = [f for f in fields if not f.combobox and f.type != "file"]
            # Required checkbox GROUPS (>=2 checkboxes sharing a name) need exactly
            # one option checked — pull their members out of the per-field resolve.
            (
                checkbox_groups,
                radio_groups,
                multi_group_keys,
                multi_radio_group_keys,
                group_member_keys,
            ) = _partition_checkbox_radio_groups(non_combo)
            from applypilot.apply.direct import profile_binding

            regular = [
                f for f in non_combo
                if f.key not in group_member_keys
                and not profile_binding.is_phantom_technology_select(f)
            ]

            # Let JS widgets (intl-tel-input, react-select) finish initializing.
            page.wait_for_timeout(1_500)

            if _verification_wall_present(_body_text_lower(page)):
                cleared, wall_reason = _try_clear_verification_wall(
                    page, job, adapter=adapter, worker_id=worker_id
                )
                if not cleared:
                    _persist_form_filled(job.get("url") or url, _form_record())
                    return done(
                        "failed:direct_needs_verification",
                        escalate=True,
                        reason=wall_reason or "email_verification_code",
                        outcome=outcome,
                        fields_total=len(fields),
                    )
                continue

            page_outcome = resolver.resolve(
                regular, tokens, job=job, gemini_enabled=gemini_enabled
            )
            if outcome is None:
                outcome = page_outcome
            else:
                outcome.tier_max = max(outcome.tier_max, page_outcome.tier_max)
                outcome.llm_field_count += page_outcome.llm_field_count
            for f in regular:
                ans = page_outcome.answers.get(f.key)
                if not ans and family == "workday" and _is_workday_search_field(f):
                    res = profile_binding.resolve_field(f, tokens)
                    if res:
                        ans = res.answer
                if ans:
                    if family == "workday" and _is_workday_search_field(f):
                        ok = _fill_workday_search_select(page, f, ans)
                    else:
                        ok = _fill_field(page, f, ans, family=family)
                    if ok:
                        filled_rows.append(
                            _record_row(f.label, ans, ftype=f.type or f.tag,
                                        via=page_outcome.via.get(f.key, ""))
                        )
                    _sleep_fill()

            unresolved_required = list(page_outcome.unresolved_required)
            unresolved_labels: list[str] = []
            regular_by_key = {f.key: f for f in regular}
            for key in page_outcome.unresolved_required:
                f = regular_by_key.get(key)
                if f:
                    unresolved_labels.append(f"{f.label[:50]} [batch]")
            for f in combos:
                status, sub = _fill_combobox(
                    page, f, tokens, gemini_enabled=gemini_enabled, family=family
                )
                if sub is not None:
                    outcome.tier_max = max(outcome.tier_max, sub.tier_max)
                    outcome.llm_field_count += sub.llm_field_count
                if status == "filled" and sub is not None:
                    filled_rows.append(
                        _record_row(f.label, sub.answers.get(f.key, ""),
                                    ftype="select", via=sub.via.get(f.key, ""))
                    )
                if status != "filled" and f.required:
                    unresolved_required.append(f.key)
                    unresolved_labels.append(f"{f.label[:50]} [{status}]")
                _sleep_fill()

            # Lever re-renders card fields after text fills; re-stamp groups.
            if family == "lever" and (multi_group_keys or multi_radio_group_keys):
                refreshed = extractor.extract_fields(page)
                fresh_non_combo = [
                    f for f in refreshed.fillable()
                    if not f.combobox and f.type != "file"
                ]
                (
                    checkbox_groups,
                    radio_groups,
                    multi_group_keys,
                    multi_radio_group_keys,
                    _refreshed_group_keys,
                ) = _partition_checkbox_radio_groups(fresh_non_combo)

            for gkey in multi_group_keys:
                members = checkbox_groups[gkey]
                question = members[0].section_header if members else ""
                from applypilot.apply.direct import profile_binding

                if profile_binding.is_technology_multi_checkbox_question(question):
                    status, pick, via = _fill_technology_checkbox_group(
                        page,
                        members,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                    )
                else:
                    status, pick, via = _fill_checkbox_group(
                        page,
                        members,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                    )
                if status == "filled":
                    filled_rows.append(
                        _record_row(
                            members[0].section_header or "checkbox group",
                            pick or "", ftype="checkbox", via=via or "group",
                        )
                    )
                elif any(m.required for m in members):
                    unresolved_required.append(gkey)
                    unresolved_labels.append(
                        f"{(members[0].section_header or members[0].label)[:50]} [group]"
                    )
                _sleep_fill()

            for gkey in multi_radio_group_keys:
                members = radio_groups[gkey]
                status, pick, via = _fill_radio_group(
                    page, members, tokens=tokens, job=job, gemini_enabled=gemini_enabled,
                )
                if status == "filled":
                    filled_rows.append(
                        _record_row(
                            members[0].section_header or "radio group",
                            pick or "", ftype="radio", via=via or "group",
                        )
                    )
                elif any(m.required for m in members):
                    unresolved_required.append(gkey)
                    unresolved_labels.append(
                        f"{(members[0].section_header or members[0].label)[:50]} [radio]"
                    )
                _sleep_fill()

            if family == "workday":
                _fill_workday_phone_device_type(page)
                _fill_workday_compliance_prompts(
                    page, tokens=tokens, filled_rows=filled_rows,
                )
                page.wait_for_timeout(300)

            if family == "workday":
                _fill_workday_fieldset_radios(
                    page,
                    tokens=tokens,
                    filled_rows=filled_rows,
                )
                page.wait_for_timeout(300)

            # Lever re-renders card fields after group fills; identity text can clear.
            if family == "lever" and (multi_group_keys or multi_radio_group_keys):
                post_group = extractor.extract_fields(page)
                post_group_empty = _required_empty_fields(post_group)
                if _empty_text_fields(post_group_empty):
                    _refill_empty_text_fields(
                        page,
                        post_group,
                        post_group_empty,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                        filled_rows=filled_rows,
                        outcome=outcome,
                        family=family,
                    )
                    page.wait_for_timeout(300)

            # Safety guard (page 1 only): if we filled NO identity field, this is
            # a search box / cookie banner / landing page, NOT an application —
            # never submit it.
            if page_num == 0 and _identity_fields_filled(filled_rows) == 0:
                logger.info(
                    "[W%d] Direct: no application form on %s "
                    "(%d fields, 0 identity filled) — not submitting",
                    worker_id, family, len(fields),
                )
                _persist_form_filled(job.get("url") or url, _form_record_stub(
                    url, job, filled_rows, ["no_application_form"]
                ))
                return done(
                    "failed:direct_no_application_form",
                    escalate=True, reason="no_application_form",
                    outcome=outcome, fields_total=len(fields),
                )

            # Upload resume/cover on any page that exposes a file input.
            if any(f.type == "file" for f in fields):
                if not cover_resolved:
                    _cl_text, _cl_txt, cover_pdf = resolve_apply_cover_letter(job)
                    cover_upload = cover_pdf or None
                    cover_resolved = True
                _upload_files(page, form, resume_pdf, cover_upload, family=family)
            if family in {"lever", "workable"}:
                post_upload = extractor.extract_fields(page)
                post_empty = _required_empty_fields(post_upload)
                if family == "lever" and _empty_radio_group_names(post_empty):
                    _refill_empty_radio_groups(
                        page,
                        post_upload,
                        post_empty,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                        filled_rows=filled_rows,
                        outcome=outcome,
                    )
                if family == "lever":
                    _refill_empty_technology_checkbox_groups(
                        page,
                        post_upload,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                        filled_rows=filled_rows,
                        outcome=outcome,
                    )
                if family in {"lever", "workable"} and _empty_text_fields(post_empty):
                    _refill_empty_text_fields(
                        page,
                        post_upload,
                        post_empty,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                        filled_rows=filled_rows,
                        outcome=outcome,
                        family=family,
                    )
            if family == "ashby":
                for label, value in _fill_ashby_required_visible_controls(page, tokens):
                    filled_rows.append(
                        _record_row(label, value, ftype="option", via="ashby")
                    )
            page.wait_for_timeout(800)

            unresolved_state["count"] = len(unresolved_required)
            _persist_form_filled(job.get("url") or url, _form_record(unresolved_labels))

            if unresolved_required:
                logger.info(
                    "[W%d] Direct unresolved required on %s p%d: %d field(s): %s",
                    worker_id, family, page_num, len(unresolved_required),
                    "; ".join(unresolved_labels[:8]),
                )
                return done(
                    "failed:direct_unresolved_required",
                    escalate=True, reason="unresolved_required",
                    outcome=outcome, fields_total=len(fields),
                )

            # Re-extract and confirm no required non-combobox field is still empty.
            verify = extractor.extract_fields(page)
            still_empty = _required_empty_fields(verify)
            if still_empty:
                _refill_empty_radio_groups(
                    page,
                    verify,
                    still_empty,
                    tokens=tokens,
                    job=job,
                    gemini_enabled=gemini_enabled,
                    filled_rows=filled_rows,
                    outcome=outcome,
                )
                if family == "lever":
                    _refill_empty_technology_checkbox_groups(
                        page,
                        verify,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                        filled_rows=filled_rows,
                        outcome=outcome,
                    )
                if family in {"lever", "workable", "workday"}:
                    _refill_empty_text_fields(
                        page,
                        verify,
                        still_empty,
                        tokens=tokens,
                        job=job,
                        gemini_enabled=gemini_enabled,
                        filled_rows=filled_rows,
                        outcome=outcome,
                        family=family,
                    )
                    if family == "workday":
                        _refill_workday_search_fields(
                            page,
                            still_empty,
                            tokens=tokens,
                            filled_rows=filled_rows,
                        )
                page.wait_for_timeout(400)
                verify = extractor.extract_fields(page)
                still_empty = _required_empty_fields(verify)
                retry_fields = [
                    f for f in still_empty
                    if f.type != "file"
                    and f.tag != "select"
                    and not (f.type == "radio" and f.name_attr)
                ]
                if retry_fields:
                    retry = resolver.resolve(
                        retry_fields, tokens, job=job, gemini_enabled=gemini_enabled,
                    )
                    outcome.tier_max = max(outcome.tier_max, retry.tier_max)
                    outcome.llm_field_count += retry.llm_field_count
                    for f in retry_fields:
                        ans = retry.answers.get(f.key)
                        if ans and _fill_field(page, f, ans, family=family):
                            filled_rows.append(
                                _record_row(f.label, ans, ftype=f.type or f.tag,
                                            via=retry.via.get(f.key, ""))
                            )
                            _sleep_fill()
                if any(f.type == "file" for f in still_empty) and family == "ashby":
                    _upload_ashby_resume(page, resume_pdf)
                page.wait_for_timeout(600)
                verify = extractor.extract_fields(page)
                still_empty = _required_empty_fields(verify)
            if still_empty:
                from applypilot.apply.direct import profile_binding

                blocking = [f"{f.label} ({f.tag}/{f.type})" for f in still_empty]
                logger.info(
                    "[W%d] Direct verify incomplete on %s p%d — %d required empty: %s",
                    worker_id, family, page_num, len(still_empty), "; ".join(blocking[:12]),
                )
                if profile_binding.remaining_gaps_are_location_traps(still_empty):
                    return done(
                        "failed:not_eligible_location",
                        escalate=False,
                        reason="location_requirement_unmet",
                        outcome=outcome,
                        fields_total=len(fields),
                    )
                return done(
                    "failed:direct_verify_incomplete",
                    escalate=True, reason=f"empty_required={len(still_empty)}",
                    outcome=outcome, fields_total=len(fields),
                )

            # Page complete and valid. Multi-step? Click Next and fill the next
            # page; otherwise drop out to the final-submit section below.
            if family == "workday":
                from applypilot.apply.direct.adapters import workday as wd_mod

                wd_state = wd_mod.detect_workday_state(page.content())
                if wd_state in {"review", "submit"}:
                    logger.info(
                        "[W%d] Direct workday: on %s — skipping advance, finalizing submit",
                        worker_id,
                        wd_state,
                    )
                    break
                _workday_fix_validation_errors(
                    page,
                    tokens=tokens,
                    filled_rows=filled_rows,
                )
            advance = _find_advance_button(page, family=family)
            if advance and page_num < max_pages - 1:
                logger.info(
                    "[W%d] Direct multi-step: page %d filled, advancing via %r",
                    worker_id, page_num, advance,
                )
                if not unblock._click_text(page, advance):
                    logger.info("[W%d] Direct multi-step: advance click missed — finalizing",
                                worker_id)
                    break
                page.wait_for_timeout(1_800)
                continue
            break
        # ---- end per-page loop ------------------------------------------------

        if outcome is None:
            return done("failed:direct_no_form", escalate=True, reason="no_form")

        if family == "workday":
            _workday_advance_until_review(
                page,
                tokens=tokens,
                filled_rows=filled_rows,
                worker_id=worker_id,
            )
            _workday_final_refill(page, tokens=tokens, filled_rows=filled_rows)

        if not cover_resolved:
            _cl_text, _cl_txt, cover_pdf = resolve_apply_cover_letter(job)
            cover_upload = cover_pdf or None
            cover_resolved = True
        final_form = extractor.extract_fields(page)
        if any(f.type == "file" for f in final_form.fields):
            _upload_files(
                page,
                final_form,
                resume_pdf,
                cover_upload,
                family=family,
            )
        _fill_optional_gaps(
            page,
            tokens=tokens,
            job=job,
            gemini_enabled=gemini_enabled,
            filled_rows=filled_rows,
            outcome=outcome,
            family=family,
        )
        _fill_cover_prose_fallback(
            page,
            cover_text=str(tokens.get("cover_letter_text") or _cl_text or ""),
            filled_rows=filled_rows,
            family=family,
        )

        audit_rows, upload_rows, audit_block = _pre_submit_audit(
            page,
            filled_rows=filled_rows,
            resume_pdf=resume_pdf or "",
            cover_pdf=cover_upload,
            worker_id=worker_id,
            family=family,
        )
        audit_record = _form_record()
        audit_record["fields"] = audit_rows
        audit_record["field_count"] = len(audit_rows)
        audit_record["pre_submit"] = True
        audit_record["uploads"] = upload_rows
        audit_record["resume_pdf"] = resume_pdf
        audit_record["cover_pdf"] = cover_upload
        _persist_form_filled(job.get("url") or url, audit_record)
        if audit_block:
            logger.info(
                "[W%d] Pre-submit audit blocked submit on %s: %s",
                worker_id,
                url[:80],
                audit_block,
            )
            if audit_block == "not_eligible_location":
                return done(
                    "failed:not_eligible_location",
                    escalate=False,
                    reason="location_requirement_unmet",
                    outcome=outcome,
                    fields_total=len(audit_rows),
                )
            return done(
                "failed:direct_verify_incomplete",
                escalate=True,
                reason=audit_block,
                outcome=outcome,
                fields_total=len(audit_rows),
            )

        # Anti-bot wall: a few employers (e.g. Airbnb) require an emailed
        # verification code before Submit activates. NOTE: do NOT treat a
        # reCAPTCHA element as a block — Greenhouse mounts an invisible v3 on
        # every form that does not stop a normal submit.
        pre_submit_body = _body_text_lower(page)
        if _verification_wall_present(pre_submit_body):
            cleared, wall_reason = _try_clear_verification_wall(
                page, job, adapter=adapter, worker_id=worker_id
            )
            if not cleared:
                _persist_form_filled(job.get("url") or url, _form_record())
                return done(
                    "failed:direct_needs_verification",
                    escalate=True,
                    reason=wall_reason or "email_verification_code",
                    outcome=outcome, fields_total=len(fields),
                )
            page.wait_for_timeout(600)

        result_dr = done("submitted_unverified:direct", outcome=outcome)
        result_dr.fields_total = len(fields)

        if dry_run:
            result_dr.result = "skipped:direct_dry_run"
            logger.info("[W%d] Direct dry-run filled %d fields across pages (no submit): %s",
                        worker_id, len(filled_rows), url[:80])
            return result_dr

        captcha_info = direct_captcha.detect_captcha_blocking(page)
        captcha_type = (captcha_info.get("type") or "").lower() if captcha_info else ""
        captcha_blocking = (
            captcha_info is not None
            and captcha_type not in direct_captcha._SKIP_TYPES
        ) or direct_captcha.turnstile_wall_visible(page)
        if captcha_blocking:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
            if not direct_captcha.solve_captcha_if_present(page):
                _persist_form_filled(job.get("url") or url, _form_record())
                return done(
                    "failed:direct_captcha",
                    escalate=True,
                    reason="captcha_unsolved",
                    outcome=outcome,
                    fields_total=len(fields),
                )
            page.wait_for_timeout(400)

        if adapter.family == "workday" and _workday_has_validation_errors(page):
            _workday_advance_until_review(
                page,
                tokens=tokens,
                filled_rows=filled_rows,
                worker_id=worker_id,
            )

        pre_url = page.url
        if not _click_submit(page, adapter):
            if adapter.family == "workday":
                try:
                    btn_dump = page.evaluate(
                        """() => [...document.querySelectorAll('button, [role="button"], input[type="submit"]')]
                          .map(b => ({
                            text: (b.innerText || b.value || b.getAttribute('aria-label') || '').trim(),
                            auto: b.getAttribute('data-automation-id'),
                          })).filter(x => x.text).slice(0, 12)"""
                    )
                    logger.info(
                        "[W%d] Workday submit missed; visible buttons=%s",
                        worker_id,
                        btn_dump,
                    )
                except Exception:  # noqa: BLE001
                    pass
            result_dr.result = "failed:direct_no_submit_button"
            result_dr.escalate = True
            result_dr.escalate_reason = "no_submit_button"
            return result_dr

        page.wait_for_timeout(int(_SUBMIT_SETTLE_S * 1000))

        # Greenhouse (and a few others) only EMAIL the 8-character human-check
        # code AFTER the first Submit click, so the wall appears here, not in the
        # pre-submit check above. Fetch the code from Gmail, enter it, and submit
        # again. If we can't get the code, escalate cleanly rather than leave a
        # filled-but-unsent form looking like a silent failure.
        post_submit_body = _body_text_lower(page)
        if _verification_wall_present(post_submit_body):
            cleared, wall_reason = _try_clear_verification_wall(
                page, job, adapter=adapter, worker_id=worker_id
            )
            if not cleared:
                shot = _screenshot(page, worker_id, family)
                after = extractor.extract_fields(page)
                _persist_form_filled(job.get("url") or url, _form_record(after.visible_errors))
                result_dr.result = "failed:direct_needs_verification"
                result_dr.escalate = True
                result_dr.escalate_reason = wall_reason or "email_verification_code"
                result_dr.elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info("[W%d] Direct verification wall not cleared on %s: %s",
                            worker_id, url[:70], wall_reason)
                return result_dr
            logger.info("[W%d] Direct cleared email verification wall on %s",
                        worker_id, url[:70])
            _click_submit(page, adapter)
            page.wait_for_timeout(int(_SUBMIT_SETTLE_S * 1000))

        post_url = page.url
        post_body = _body_text_lower(page)
        after = extractor.extract_fields(page)
        shot = _screenshot(page, worker_id, family)
        final_record = dict(audit_record)
        if after.visible_errors:
            final_record["visible_errors"] = after.visible_errors
        final_record["submitted"] = True
        _persist_form_filled(job.get("url") or url, final_record)

        # A genuine submission removes the form (Greenhouse shows a "Thank you"
        # page; the form fields + submit button disappear). Decide from:
        #   success  := success-marker text, OR url->confirmation, OR form gone
        #   rejected := form still present WITH visible validation errors
        #   not-sent := form still fully present, no success, no error caught
        # "form still present" must NOT be called a success — that was the false
        # positive that marked still-on-the-form Cloudflare jobs as submitted.
        url_changed = post_url != pre_url and not post_url.rstrip("/").endswith(
            "application"
        )
        form_present = bool(after.submit_candidates) and len(after.fillable()) >= 2
        form_gone = not form_present
        success = (
            _matches_any(post_body, adapter.success_markers)
            or url_changed
            or form_gone
        )

        if success:
            result_dr.result = "applied"
            if used_nav_sigs:
                try:
                    from applypilot.apply.direct.playbook import stamp_verified

                    stamp_verified(used_nav_sigs, scope="host")
                except Exception:  # noqa: BLE001
                    logger.debug("stamp_verified failed", exc_info=True)
            logger.info("[W%d] Direct APPLIED %s (shot=%s)", worker_id, url[:70], shot)
        elif after.visible_errors:
            if _is_transient_submit_error(after.visible_errors):
                result_dr.result = "failed:direct_transient_submit"
                result_dr.escalate = False
                result_dr.escalate_reason = "transient:" + "; ".join(
                    after.visible_errors[:2]
                )
                logger.info(
                    "[W%d] Direct submit transient error (retry later) %s: %s",
                    worker_id,
                    url[:70],
                    after.visible_errors[:2],
                )
            else:
                result_dr.result = "failed:direct_submit_rejected"
                result_dr.escalate = True
                result_dr.escalate_reason = "submit_rejected:" + "; ".join(
                    after.visible_errors[:4]
                )
                logger.info("[W%d] Direct submit REJECTED %s: %s",
                            worker_id, url[:70], after.visible_errors[:4])
        else:
            post_captcha = direct_captcha.detect_captcha_blocking(page, wait_s=1.5)
            if (
                direct_captcha.is_blocking_captcha(post_captcha)
                or direct_captcha.turnstile_wall_visible(page)
                or "verify you are human" in post_body
            ):
                result_dr.result = "failed:direct_captcha"
                result_dr.escalate = True
                result_dr.escalate_reason = "captcha_unsolved"
                logger.info(
                    "[W%d] Direct NOT confirmed — captcha still present %s (shot=%s)",
                    worker_id, url[:70], shot,
                )
            elif "verify you are human" in post_body or (
                "cloudflare" in post_body and "turnstile" in post_body
            ):
                result_dr.result = "failed:direct_captcha"
                result_dr.escalate = True
                result_dr.escalate_reason = "captcha_unsolved"
                logger.info(
                    "[W%d] Direct NOT confirmed — Turnstile wall %s (shot=%s)",
                    worker_id, url[:70], shot,
                )
            else:
                result_dr.result = "failed:direct_not_submitted"
                result_dr.escalate = True
                result_dr.escalate_reason = "no_confirmation"
                logger.info(
                    "[W%d] Direct NOT confirmed (form still present) %s (shot=%s)",
                    worker_id, url[:70], shot,
                )
        result_dr.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result_dr
    except Exception as exc:  # noqa: BLE001
        if adapter is None:
            # Unknown family we never managed to load or content-sniff (e.g. the
            # browser was unreachable): escalate as no_adapter, matching the
            # URL-only verdict instead of surfacing a generic crash.
            return done("failed:direct_no_adapter", escalate=True, reason="no_adapter")
        logger.warning("Direct apply crashed for %s: %s", url[:80], exc)
        return done("failed:direct_exception", escalate=True, reason=str(exc)[:80])
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            pw.stop()
        except Exception:  # noqa: BLE001
            pass
