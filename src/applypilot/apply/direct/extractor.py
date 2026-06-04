"""Form extractor — the selector bridge between DOM and Driver.

FORM_VERIFY_JS (prompt_scripts.py) can *describe* a form but returns no locator,
so it can't *drive* one. This extends it: every fillable field gets a stable
locator stamp (`data-ap-id` + content `data-ap-key`), its options enumerated,
its required flag, and its nearest section header (the disambiguator the Q&A
bank keys on).

    page ──extract_fields()──► FormState
                                 ├─ fields: [Field(..., key, ap_id, options)]
                                 ├─ empty_required, visible_errors
                                 ├─ submit_candidates, body_text, url
                                 └─ partial  (True when a widget couldn't be read)

Stamping survives React re-render two ways (docs/direct-apply-architecture.md
§6.3): the Driver re-stamps immediately before each fill, and the content
`key` (hash of label+name+section+index) is the primary identity with the
ordinal `ap_id` as fallback. The Driver locates fields by
`[data-ap-key="..."]`, falling back to `[data-ap-id="..."]`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field

from applypilot.apply.direct.profile_binding import Field

logger = logging.getLogger(__name__)

# JS run in the page. Stamps every fillable element and returns a rich record.
# Single self-contained function so it can be page.evaluate()'d directly.
EXTRACT_JS = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0 || el.type === 'hidden';
  };
  const sectionOf = (el) => {
    // Nearest fieldset legend, else preceding heading.
    const fs = el.closest('fieldset');
    if (fs) {
      const lg = fs.querySelector('legend');
      if (lg) return norm(lg.innerText).slice(0, 80);
    }
    let node = el;
    for (let i = 0; i < 6 && node; i++) {
      node = node.previousElementSibling || node.parentElement;
      if (node && /^H[1-6]$/.test(node.tagName)) return norm(node.innerText).slice(0, 80);
    }
    return '';
  };
  const labelledbyText = (el) => {
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (!ids.length) return '';
    return ids.map((id) => { const t = document.getElementById(id); return t ? t.innerText : ''; })
              .join(' ');
  };
  // Ashby and many custom forms associate the question with the field via a
  // sibling/ancestor <label> (not for=/aria-labelledby), so the standard label
  // sources come back empty and we'd fall to a useless placeholder
  // ("Pick date...", "Start typing..."). Walk up a few levels and take the
  // nearest container's label — closest ancestor first, so we get THIS field's
  // question, not a neighbour's.
  const ancestorLabel = (el) => {
    let n = el;
    for (let i = 0; i < 6 && n; i++) {
      n = n.parentElement;
      if (!n) break;
      const lab = n.querySelector('label, legend, [class*="label"], [class*="Label"], [class*="title"], [class*="Title"]');
      if (lab && !lab.contains(el)) {
        const t = norm(lab.innerText);
        if (t.length > 2 && t.length < 120) return t;
      }
    }
    return '';
  };
  const labelOf = (el) => {
    const strong = norm(
      (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute('aria-label') ||
      labelledbyText(el)
    );
    if (strong) return strong.slice(0, 120);
    const anc = ancestorLabel(el);
    if (anc) return anc.slice(0, 120);
    return norm(
      el.getAttribute('placeholder') || el.name || el.id || el.type || 'field'
    ).slice(0, 120);
  };
  const isCombobox = (el) =>
    el.getAttribute('role') === 'combobox' || /select__input/.test(el.className || '');
  const isMultiSelect = (el) => {
    const ctrl = el.closest('.select__control');
    return !!(ctrl && ctrl.classList.contains('select__control--is-multi'));
  };

  const sha = (str) => {
    // Tiny non-crypto hash; stable enough for a per-form content key.
    let h = 0;
    for (let i = 0; i < str.length; i++) { h = (h * 31 + str.charCodeAt(i)) | 0; }
    return (h >>> 0).toString(16);
  };

  const fields = [];
  let partial = false;
  const seenKeys = {};
  let idx = 0;

  // React-select (Greenhouse's modern job-boards form, Ashby, etc.) renders a
  // hidden <input ... requiredInput> with tabindex="-1" inside the select
  // container purely to drive native required-validation. It is NOT a field —
  // it mirrors the sibling role=combobox and is populated when an option is
  // picked. Treating it as a standalone required text input made every such
  // form escalate (unresolved_required) or fail the final empty-required guard.
  const isSelectRequiredProxy = (el) => {
    if (el.tagName.toLowerCase() !== 'input') return false;
    if (el.getAttribute('role') === 'combobox') return false;
    if (/requiredInput/i.test(el.className || '')) return true;
    return el.getAttribute('tabindex') === '-1'
      && !!el.closest('.select__container, .select-shell, .select__control, .select');
  };

  const els = document.querySelectorAll('input, select, textarea, [role="combobox"], [role="listbox"], [role="radiogroup"]');
  els.forEach((el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || el.type || '').toLowerCase();
    if (tag === 'input' && type === 'hidden') return;
    if (isSelectRequiredProxy(el)) return;
    // Individual radios inside a radiogroup are filled via the group's options.
    if (tag === 'input' && type === 'radio' && el.closest('[role="radiogroup"]')) return;
    if (!visible(el) && type !== 'hidden') {
      // styled-hidden file/date inputs are kept; truly invisible noise is not.
      if (!(type === 'file' || tag === 'input')) return;
    }
    const label = labelOf(el);
    const section = sectionOf(el);
    const name = norm(el.getAttribute('name') || el.id || '');
    const autocomplete = norm(el.getAttribute('autocomplete') || '');
    const required = el.required || el.getAttribute('aria-required') === 'true';

    let options = [];
    if (tag === 'select') {
      options = [...el.options].map((o) => norm(o.text)).filter(Boolean);
    } else if (el.getAttribute('role') === 'radiogroup') {
      options = [...el.querySelectorAll('[role="radio"]')].map((o) => norm(o.innerText)).filter(Boolean);
    } else if (el.getAttribute('role') === 'listbox' || el.getAttribute('role') === 'combobox') {
      options = [...el.querySelectorAll('[role="option"]')].map((o) => norm(o.innerText)).filter(Boolean);
    }

    let value = '';
    if (type === 'checkbox' || type === 'radio') value = el.checked ? 'checked' : '';
    else if (tag === 'select') value = norm(el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value);
    else value = (el.value || '').slice(0, 200);

    const keyBase = `${label}|${name}|${section}|${tag}|${type}`;
    let key = sha(keyBase);
    if (seenKeys[key]) { key = sha(keyBase + '#' + idx); }  // collision -> include index
    seenKeys[key] = 1;

    el.setAttribute('data-ap-id', String(idx));
    el.setAttribute('data-ap-key', key);

    fields.push({
      key, ap_id: idx, label, tag, type, name, autocomplete,
      section_header: section, required: !!required,
      options, value, empty: !String(value).trim(),
      combobox: isCombobox(el),
      is_multi: isMultiSelect(el),
    });
    idx++;
  });

  // Out-of-DOM widgets we cannot read -> flag the form partial so the Driver
  // escalates instead of submitting half-filled.
  if (document.querySelector('canvas[role], [data-widget="signature"]')) partial = true;

  const errorNodes = new Set();
  const pushErr = (el) => {
    const t = norm(el.innerText);
    if (t.length > 2 && t.length < 200) errorNodes.add(t);
  };
  document.querySelectorAll('[role="alert"], [class*="error"], [class*="invalid"]').forEach(pushErr);
  document.querySelectorAll('[aria-invalid="true"]').forEach((el) => {
    pushErr(el);
    const sib = el.nextElementSibling;
    if (sib) pushErr(sib);
    const errId = el.getAttribute('aria-describedby');
    if (errId) {
      const node = document.getElementById(errId);
      if (node) pushErr(node);
    }
  });
  document.querySelectorAll('.field-error, [id$="-error"]').forEach(pushErr);
  const errors = [...errorNodes].slice(0, 12);
  const buttons = [...document.querySelectorAll('button, [role="button"], input[type="submit"]')]
    .filter(visible).map((b) => norm(b.innerText || b.value || b.getAttribute('aria-label'))).filter(Boolean).slice(0, 15);

  return {
    url: location.href,
    title: document.title.slice(0, 160),
    body_text: norm(document.body ? document.body.innerText : '').slice(0, 6000),
    fields,
    empty_required: fields.filter((f) => f.required && f.empty).length,
    visible_errors: errors,
    submit_candidates: buttons,
    partial,
  };
}"""

# Re-stamp a single field just before fill (React may have wiped the attr).
RESTAMP_JS = r"""(args) => {
  const { key, ap_id } = args;
  // Best-effort: nothing to do if the element still carries the attribute.
  const byKey = document.querySelector(`[data-ap-key="${key}"]`);
  if (byKey) return true;
  // Re-stamp by ordinal among current fillable elements.
  const els = document.querySelectorAll('input, select, textarea, [role="combobox"], [role="listbox"], [role="radiogroup"]');
  if (ap_id >= 0 && ap_id < els.length) {
    els[ap_id].setAttribute('data-ap-key', key);
    els[ap_id].setAttribute('data-ap-id', String(ap_id));
    return true;
  }
  return false;
}"""


@dataclass
class FormState:
    """A snapshot of the current form, with drivable field locators."""

    url: str = ""
    title: str = ""
    body_text: str = ""
    fields: list[Field] = dc_field(default_factory=list)
    empty_required: int = 0
    visible_errors: list[str] = dc_field(default_factory=list)
    submit_candidates: list[str] = dc_field(default_factory=list)
    partial: bool = False

    def fillable(self) -> list[Field]:
        """Fields worth resolving (skip checkbox/radio handled as groups? keep all)."""
        return [f for f in self.fields if f.type != "hidden"]


def _to_field(raw: dict) -> Field:
    return Field(
        label=raw.get("label", ""),
        type=raw.get("type", ""),
        tag=raw.get("tag", ""),
        name_attr=raw.get("name", ""),
        autocomplete=raw.get("autocomplete", ""),
        section_header=raw.get("section_header", ""),
        required=bool(raw.get("required")),
        options=tuple(raw.get("options") or ()),
        key=raw.get("key", ""),
        ap_id=int(raw.get("ap_id", -1)),
        value=str(raw.get("value") or ""),
        empty=bool(raw.get("empty", True)),
        combobox=bool(raw.get("combobox", False)),
        is_multi=bool(raw.get("is_multi", False)),
    )


def parse_form_state(raw: dict) -> FormState:
    """Pure: turn the EXTRACT_JS return value into a FormState (unit-testable)."""
    return FormState(
        url=raw.get("url", ""),
        title=raw.get("title", ""),
        body_text=raw.get("body_text", ""),
        fields=[_to_field(f) for f in (raw.get("fields") or [])],
        empty_required=int(raw.get("empty_required", 0)),
        visible_errors=list(raw.get("visible_errors") or []),
        submit_candidates=list(raw.get("submit_candidates") or []),
        partial=bool(raw.get("partial")),
    )


def extract_fields(page) -> FormState:
    """Run EXTRACT_JS in the page (stamping locators) and return a FormState."""
    raw = page.evaluate(EXTRACT_JS)
    return parse_form_state(raw)


def restamp(page, field: Field) -> bool:
    """Re-assert a field's locator attributes right before filling it."""
    try:
        return bool(page.evaluate(RESTAMP_JS, {"key": field.key, "ap_id": field.ap_id}))
    except Exception:  # noqa: BLE001
        return False
