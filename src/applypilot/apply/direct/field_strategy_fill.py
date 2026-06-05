"""Self-learning field fill — replay field_strategy before default heuristics."""

from __future__ import annotations

import logging

from applypilot.apply.direct import extractor
from applypilot.apply.direct.qa_bank import question_key

logger = logging.getLogger(__name__)

try:
    from applypilot.apply.direct import playbook as _playbook
except ImportError:  # pragma: no cover
    _playbook = None

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
  const labels = [...document.querySelectorAll('label, legend, [class*="question-title"], [class*="Question"], [class*="label"], [class*="Label"]')];
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


def field_sig(field) -> str:
    """Stable key for field_strategy rows (mirrors qa_bank.question_key)."""
    return question_key(
        field.label,
        section_header=field.section_header,
        name_attr=field.name_attr,
        answer_type=field.type or field.tag or "text",
    )


def infer_fill_method(
    field,
    family: str,
    *,
    succeeded: bool,
    used_click_label: bool,
) -> str:
    """Infer which fill primitive worked (for write-back)."""
    _ = family
    if not succeeded:
        return "value"
    if used_click_label:
        return "click_label"
    if field.type == "tel":
        return "press_sequentially"
    if field.combobox or (field.tag == "select" and field.options):
        return "react_select"
    if field.tag == "select":
        return "value"
    if field.type == "checkbox":
        return "click_label" if used_click_label else "value"
    return "value"


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


def _click_option_near_label(page, field, answer: str) -> bool:
    try:
        return bool(
            page.evaluate(
                _CLICK_OPTION_NEAR_LABEL_JS,
                {"label": field.label, "answer": answer},
            )
        )
    except Exception:  # noqa: BLE001
        logger.debug("click_label failed for %r", field.label, exc_info=True)
        return False


def _fill_value(page, field, answer: str) -> bool:
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
    loc.fill(answer, timeout=5_000)
    return True


def _fill_click_label(page, field, answer: str, *, family: str) -> bool:
    loc = _locator(page, field)
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed(timeout=3_000)
    if field.type == "checkbox":
        want = answer.strip().lower() in ("yes", "true", "checked", "on", "1")
        if not want:
            return True
        try:
            loc.check(timeout=3_000)
        except Exception:  # noqa: BLE001
            return _click_option_near_label(page, field, answer)
        try:
            if not loc.is_checked():
                return _click_option_near_label(page, field, answer)
        except Exception:  # noqa: BLE001
            pass
        return True
    if field.type == "radio" and family == "ashby":
        return _click_option_near_label(page, field, answer)
    return _click_option_near_label(page, field, answer)


def _fill_press_sequentially(page, field, answer: str) -> bool:
    loc = _locator(page, field)
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed(timeout=3_000)
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


def _fill_react_select(page, field, answer: str, *, family: str) -> bool:
    from applypilot.apply.direct import profile_binding

    if field.tag == "select" and field.options:
        pick = profile_binding.choose_select_option(answer, field.options)
        if not pick:
            return False
        loc = _locator(page, field)
        try:
            loc.select_option(label=pick)
            return True
        except Exception:  # noqa: BLE001
            try:
                loc.select_option(value=pick)
                return True
            except Exception:  # noqa: BLE001
                return False

    if not field.combobox:
        return _fill_value(page, field, answer)

    try:
        page.evaluate(_MARK_COMBO_JS, field.label or "")
    except Exception:  # noqa: BLE001
        return False
    opener = page.locator('[data-ap-open="1"]').first
    if opener.count() == 0:
        return False
    try:
        opener.click(timeout=4_000)
    except Exception:  # noqa: BLE001
        return False
    page.wait_for_timeout(400)
    sel = (
        '.select__menu .select__option, .select__menu [role="option"]'
        if family != "ashby"
        else '[role="listbox"] [role="option"], [data-headlessui-state] [role="option"]'
    )
    option = page.locator(sel).filter(has_text=answer).first
    if option.count() == 0:
        option = page.get_by_role("option", name=answer, exact=False).first
    if option.count() == 0:
        return False
    option.click(timeout=4_000)
    return True


def _lookup_method(field, family: str) -> str | None:
    if _playbook is None:
        return None
    lookup = getattr(_playbook, "lookup_field_strategy", None)
    if not callable(lookup):
        return None
    return lookup(field_sig(field), family)


def fill_field_with_strategy(page, field, answer: str, *, family: str) -> bool:
    """Try cached fill_method first, then driver-like defaults."""
    method = _lookup_method(field, family)
    if method == "click_label":
        return _fill_click_label(page, field, answer, family=family)
    if method == "press_sequentially":
        return _fill_press_sequentially(page, field, answer)
    if method == "react_select":
        return _fill_react_select(page, field, answer, family=family)
    if method == "value":
        return _fill_value(page, field, answer)

    # Default heuristics (mirror driver._fill_field order).
    if field.tag == "select" or field.combobox:
        if field.type == "tel":
            return _fill_press_sequentially(page, field, answer)
        if field.combobox or field.options:
            return _fill_react_select(page, field, answer, family=family)
    if field.type == "checkbox":
        return _fill_click_label(page, field, answer, family=family)
    if field.type == "tel":
        return _fill_press_sequentially(page, field, answer)
    return _fill_value(page, field, answer)


def record_fill_outcome(field, family: str, method: str, success: bool) -> None:
    """Write-back fill_method outcome to field_strategy."""
    if _playbook is None:
        return
    sig = field_sig(field)
    if success:
        _playbook.record_field_strategy(sig, family, method)
    else:
        bump = getattr(_playbook, "bump_field_fail", None)
        if callable(bump):
            bump(sig, family)
