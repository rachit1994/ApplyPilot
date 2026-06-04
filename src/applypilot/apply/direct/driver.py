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
import random
import time
from dataclasses import dataclass
from pathlib import Path

from applypilot import config
from applypilot.apply import apply_settings
from applypilot.apply.direct import extractor, fingerprint, profile_binding, resolver
from applypilot.apply.direct import captcha as direct_captcha
from applypilot.apply.direct import email_verify
from applypilot.apply.direct.adapters import Adapter, get_adapter
from applypilot.apply.prompt import ensure_resume_pdf
from applypilot.role_resumes import resolve_job_resume_path

logger = logging.getLogger(__name__)

# Tunables (kept conservative; humanization is volume-shaping, not impersonation).
_NAV_TIMEOUT_MS = 45_000
_FILL_DELAY = (0.15, 0.5)        # pause between fields
_SUBMIT_SETTLE_S = 6.0           # wait after submit click before reading result
_RESUME_LABEL_HINTS = ("resume", "cv", "résumé", "curriculum")
_COVER_LABEL_HINTS = ("cover letter", "cover_letter", "coverletter")


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
    """Rewrite custom-domain Greenhouse links to the hosted embedded form.

    Many employers embed Greenhouse on their own careers site
    (careers.datadoghq.com/detail/123?gh_jid=123, databricks.com/...?gh_jid=...).
    Those pages render the JD, not a fillable form, so the Driver saw 'no_form'
    or the wrong submit button. The job's real application form is always at
    boards.greenhouse.io/embed/job_app?token=<gh_jid>; navigate straight there.
    """
    if family != "greenhouse":
        return url
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(url)
    if "greenhouse.io" in parts.netloc.lower():
        return url  # already a native Greenhouse-hosted form
    token = (parse_qs(parts.query).get("gh_jid") or [None])[0]
    if token:
        return f"https://boards.greenhouse.io/embed/job_app?token={token}"
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
    form_url = fingerprint.greenhouse_form_url(urls) if family == "greenhouse" else None
    return family, form_url


def _record_row(label: str, value: str, *, ftype: str, via: str) -> dict:
    """One field row in the dashboard's apply_form_filled shape."""
    return {
        "label": label,
        "value": value,
        "type": ftype or "text",
        "empty": not str(value or "").strip(),
        "source": f"direct:{via}" if via else "direct",
    }


def _persist_form_filled(url: str, record: dict) -> None:
    """Save the per-company filled-values record so the dashboard can show it."""
    try:
        import json as _json

        from applypilot.database import get_connection
        conn = get_connection()
        conn.execute(
            "UPDATE jobs SET apply_form_filled = ? WHERE url = ?",
            (_json.dumps(record, ensure_ascii=False), url),
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


def _fill_field(page, field, answer: str) -> bool:
    """Fill one resolved field. Returns True on success."""
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
                loc.check(timeout=3_000)
                return True
            return False
        if field.type == "checkbox":
            want = answer.strip().lower() in ("yes", "true", "checked", "on", "1")
            if want:
                loc.check(timeout=3_000)
            return True
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


def _fill_checkbox_group(page, members) -> tuple[str, str | None]:
    """Check exactly ONE option in a required checkbox group (e.g. 'how did you
    hear about us'). Returns (status, picked_label) with status in
    {'filled', 'unresolved'}; 'unresolved' means we won't guess (escalate)."""
    labels = tuple(m.label for m in members)
    question = next((m.section_header for m in members if m.section_header), "")
    pick = profile_binding.choose_checkbox_group_option(question, labels)
    if not pick:
        return "unresolved", None
    target = next((m for m in members if m.label == pick), None)
    if target is None:
        return "unresolved", None
    try:
        loc = _locator(page, target)
        if loc.count() == 0:
            return "unresolved", None
        loc.scroll_into_view_if_needed(timeout=3_000)
        loc.check(timeout=4_000)
        return "filled", pick
    except Exception:  # noqa: BLE001
        logger.debug("checkbox group fill failed for %r", question, exc_info=True)
        return "unresolved", None


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


def _upload_files(page, form, resume_pdf: str, cover_pdf: str | None) -> None:
    for f in form.fields:
        if f.type != "file":
            continue
        # Use label + name + section so the resume/cover inputs (both labelled
        # "Attach" on modern Greenhouse) are told apart by their name/id.
        hint = f"{f.label} {f.name_attr} {f.section_header}".lower()
        is_cover = any(h in hint for h in _COVER_LABEL_HINTS)
        if is_cover:
            if not cover_pdf or not Path(cover_pdf).exists():
                continue
            target = cover_pdf
        else:
            # Any non-cover file input defaults to the resume.
            target = resume_pdf
        try:
            _file_input_locator(page, f).set_input_files(target, timeout=8_000)
            _wait_upload_complete(page)
        except Exception:  # noqa: BLE001
            logger.debug("file upload failed for %r", f.label, exc_info=True)


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
    "enter the code we sent",
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

    company = str(job.get("site") or job.get("company") or "").strip()
    since = time.time() - 120.0
    code_input = _locate_code_input(page)

    if code_input is None or code_input.count() == 0:
        _click_submit(page, adapter)
        page.wait_for_timeout(2_000)
        code_input = _locate_code_input(page)

    code_len = 8
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

    if code_input is None or code_input.count() == 0:
        return False, "email_verification_code"

    try:
        code_input.fill(code, timeout=5_000)
        page.wait_for_timeout(400)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to fill verification code", exc_info=True)
        return False, "email_verification_code"

    if apply_settings.captcha_solving_enabled():
        if not direct_captcha.solve_recaptcha_v2_if_present(page):
            logger.info("[W%d] reCAPTCHA v2 present but not solved", worker_id)
            return False, "captcha_unsolved"

    return True, None


def _click_submit(page, adapter: Adapter) -> bool:
    for text in adapter.submit_button_texts:
        try:
            btn = page.get_by_role("button", name=text, exact=False).first
            if btn.count() == 0:
                btn = page.locator(f'input[type="submit"][value*="{text}" i]').first
            if btn.count() > 0:
                btn.scroll_into_view_if_needed(timeout=3_000)
                btn.click(timeout=8_000)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


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
_OPTION_SELECTOR = _OPTION_SELECTOR_GREENHOUSE


def _option_selector(family: str) -> str:
    if family == "ashby":
        return _OPTION_SELECTOR_ASHBY
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
    if adapter is None and not can_content_sniff:
        return done("failed:direct_no_adapter", escalate=True, reason="no_adapter")
    if not url:
        return done("failed:direct_no_url", escalate=True, reason="no_url")

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
        page.wait_for_timeout(1_200)

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
        form = extractor.extract_fields(page)
        fields = form.fillable()
        if form.partial:
            return done("failed:direct_partial_form", escalate=True, reason="partial_form")
        if len(fields) < 2:
            return done("failed:direct_no_form", escalate=True, reason="no_form")

        tokens = _build_tokens(job, resume_pdf)
        # Three field classes, each handled differently:
        #   - file       -> _upload_files (never the answer resolver)
        #   - combobox   -> opened individually, resolved against live options
        #   - regular    -> one upfront batch resolve + fill
        combos = [f for f in fields if f.combobox]
        non_combo = [f for f in fields if not f.combobox and f.type != "file"]
        # Required checkbox GROUPS (>=2 checkboxes sharing a name, e.g. the
        # "how did you hear about us?" multi-select) need exactly one option
        # checked — not one answer per member. Pull their members out of the
        # per-field resolve so each isn't treated as a standalone required field.
        checkbox_groups: dict[str, list] = {}
        for f in non_combo:
            if f.type == "checkbox" and f.name_attr:
                checkbox_groups.setdefault(f.name_attr, []).append(f)
        multi_group_keys = [k for k, v in checkbox_groups.items() if len(v) > 1]
        group_member_keys = {
            f.key for k in multi_group_keys for f in checkbox_groups[k]
        }
        regular = [f for f in non_combo if f.key not in group_member_keys]

        # Let JS widgets (intl-tel-input, react-select) finish initializing
        # before filling; otherwise a value set too early is misparsed (e.g. an
        # international phone read as an over-long US number).
        page.wait_for_timeout(1_500)

        outcome = resolver.resolve(
            regular, tokens, job=job, gemini_enabled=gemini_enabled
        )
        filled_rows: list[dict] = []  # what we actually put on the form (per company)
        for f in regular:
            ans = outcome.answers.get(f.key)
            if ans:
                if _fill_field(page, f, ans):
                    filled_rows.append(
                        _record_row(f.label, ans, ftype=f.type or f.tag,
                                    via=outcome.via.get(f.key, ""))
                    )
                _sleep_fill()

        unresolved_required = list(outcome.unresolved_required)
        unresolved_labels: list[str] = []
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

        for gkey in multi_group_keys:
            members = checkbox_groups[gkey]
            status, pick = _fill_checkbox_group(page, members)
            if status == "filled":
                filled_rows.append(
                    _record_row(
                        members[0].section_header or "checkbox group",
                        pick or "", ftype="checkbox", via="group",
                    )
                )
            elif any(m.required for m in members):
                unresolved_required.append(gkey)
                unresolved_labels.append(
                    f"{(members[0].section_header or members[0].label)[:50]} [group]"
                )
            _sleep_fill()

        def _form_record(extra_errors=None) -> dict:
            return {
                "form_url": url,
                "page_title": (job.get("title") or "")[:160],
                "company": job.get("site") or "",
                "fields": filled_rows,
                "fill_actions": [],
                "visible_errors": list(extra_errors or []),
                "empty_required": len(unresolved_required),
                "field_count": len(filled_rows),
                "engine": "direct",
            }

        from applypilot.apply.cover_resolve import resolve_apply_cover_letter

        _cl_text, _cl_txt, cover_pdf = resolve_apply_cover_letter(job)
        cover_upload = cover_pdf or None
        _upload_files(page, form, resume_pdf, cover_upload)
        page.wait_for_timeout(800)

        _persist_form_filled(job.get("url") or url, _form_record(unresolved_labels))

        if unresolved_required:
            logger.info(
                "[W%d] Direct unresolved required on %s: %d field(s): %s",
                worker_id, family, len(unresolved_required),
                "; ".join(unresolved_labels[:8]),
            )
            return done(
                "failed:direct_unresolved_required",
                escalate=True, reason="unresolved_required",
                outcome=outcome, fields_total=len(fields),
            )

        # Final guard: re-extract and confirm no required *non-combobox* field is
        # still empty (react-select keeps its selection outside input.value, so
        # comboboxes are trusted from the fill step above, not re-read here).
        verify = extractor.extract_fields(page)
        # A required checkbox GROUP is satisfied once any one member is checked;
        # the other members staying empty is expected, not a blocking gap.
        checked_group_names = {
            f.name_attr for f in verify.fields
            if f.type == "checkbox" and f.name_attr and str(f.value).strip()
        }
        still_empty = [
            f for f in verify.fields
            if f.required and not f.combobox and not str(f.value).strip()
            and not (f.type == "checkbox" and f.name_attr in checked_group_names)
        ]
        if still_empty:
            blocking = [f"{f.label} ({f.tag}/{f.type})" for f in still_empty]
            logger.info(
                "[W%d] Direct verify incomplete on %s — %d required empty: %s",
                worker_id, family, len(still_empty), "; ".join(blocking[:12]),
            )
            return done(
                "failed:direct_verify_incomplete",
                escalate=True, reason=f"empty_required={len(still_empty)}",
                outcome=outcome, fields_total=len(fields),
            )

        # Anti-bot wall: a few employers (e.g. Airbnb) require an emailed
        # verification code before Submit activates. The deterministic engine
        # can't read email — that's the Claude+Gmail path's job — so detect this
        # specific blocking wall and escalate cleanly. NOTE: do NOT treat a
        # reCAPTCHA element as a block — Greenhouse mounts an invisible
        # reCAPTCHA v3 on every form that does not stop a normal submit; keying
        # off it flags every clean form as "needs verification" (false positive).
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
            logger.info("[W%d] Direct dry-run filled %d fields (no submit): %s",
                        worker_id, len(fields), url[:80])
            return result_dr

        pre_url = page.url
        if not _click_submit(page, adapter):
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
        _persist_form_filled(job.get("url") or url, _form_record(after.visible_errors))

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
            logger.info("[W%d] Direct APPLIED %s (shot=%s)", worker_id, url[:70], shot)
        elif after.visible_errors:
            result_dr.result = "failed:direct_submit_rejected"
            result_dr.escalate = True
            result_dr.escalate_reason = "submit_rejected:" + "; ".join(
                after.visible_errors[:4]
            )
            logger.info("[W%d] Direct submit REJECTED %s: %s",
                        worker_id, url[:70], after.visible_errors[:4])
        else:
            # Form still on screen, no confirmation and no error we could read:
            # treat as NOT submitted so it parks/escalates for a clean retry
            # rather than being falsely recorded as applied.
            result_dr.result = "failed:direct_not_submitted"
            result_dr.escalate = True
            result_dr.escalate_reason = "no_confirmation"
            logger.info("[W%d] Direct NOT confirmed (form still present) %s (shot=%s)",
                        worker_id, url[:70], shot)
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
