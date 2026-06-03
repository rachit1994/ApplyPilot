"""Resolver Tier 0 — deterministic profile binding (rules, $0).

Python port of the FIELD MAP + QUESTION MAP from docs/worker-apply-playbook.md.
Covers ~70% of fields (name, email, phone, URLs, work auth, salary, EEO, the
standard yes/no screening set) with zero LLM calls.

Match precedence (docs/direct-apply-architecture.md §4 Tier 0): resolve in this
order, and return None (escalate) rather than guess on ambiguity —

    1. HTML attribute  (name / autocomplete / type=email|tel|url)  -- author-set, stable
    2. label + section (a "Name" under "Referrer" binds to referrer, not you)
    3. bare label      (only when 1 & 2 give no signal)

Guessing is a worse failure than escalating: a wrong value in a real employer
form is a quality defect, an escalation just costs one cheap Gemini call.

Values come from worker_playbook.build_playbook_tokens — the SAME source the
seed and the live fill use, so Tier 0 answers can never drift from the profile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

# ---------------------------------------------------------------------------
# Field descriptor handed in by the extractor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One fillable form field, as seen by the extractor."""

    label: str = ""
    type: str = ""              # html input type: text|email|tel|select|checkbox|radio|...
    tag: str = ""               # input|select|textarea
    name_attr: str = ""         # name / id attribute
    autocomplete: str = ""      # autocomplete attribute
    section_header: str = ""    # nearest <legend>/<h*> — disambiguator
    required: bool = False
    options: tuple[str, ...] = dc_field(default_factory=tuple)  # for select/radio
    key: str = ""               # stable content key from the extractor (locator id)
    ap_id: int = -1             # ordinal fallback locator id
    value: str = ""             # current value as seen by the extractor
    empty: bool = True          # True when the field has no value yet
    combobox: bool = False      # react-select / role=combobox (options load on open)


@dataclass(frozen=True)
class Resolution:
    """A Tier-0 answer with provenance for telemetry/debugging."""

    answer: str
    confidence: float
    via: str  # 'attr' | 'label' | 'free_text'


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


# ---------------------------------------------------------------------------
# FIELD MAP — label substring -> token key (or a derive function)
# Ordered: first match wins. Mirrors worker-apply-playbook.md FIELD MAP.
# ---------------------------------------------------------------------------

def _first_word(tokens: dict) -> str:
    return (tokens.get("full_name") or "").split()[0] if tokens.get("full_name") else ""


def _last_word(tokens: dict) -> str:
    parts = (tokens.get("full_name") or "").split()
    return parts[-1] if len(parts) > 1 else ""


# Each rule: (list of label substrings, token_key OR callable(tokens)->str)
FIELD_MAP: tuple[tuple[tuple[str, ...], object], ...] = (
    (("first name",), _first_word),
    (("last name", "surname", "family name"), _last_word),
    (("full name", "your name", "legal name"), "full_name"),
    (("preferred name",), "preferred_name"),
    (("email",), "email"),
    (("phone", "mobile", "telephone"), "phone_e164"),
    (("address", "street"), "address"),
    (("city", "town"), "city"),
    (("state", "province"), "province_state"),
    (("country",), "country"),
    (("zip", "postal"), "postal_code"),
    (("linkedin",), "linkedin_url"),
    (("github",), "github_url"),
    (("portfolio", "website", "personal site"), "portfolio_url"),
    (("current title", "current job title", "most recent title"), "current_job_title"),
    (("years of experience", "years experience"), "years_experience"),
    (("education", "degree", "highest level"), "education_level"),
    (("salary", "compensation", "expected pay", "desired salary"), "salary_number"),
    (("start date", "available", "notice period"), "earliest_start_date"),
)

# HTML autocomplete / name attribute -> token key. Checked BEFORE label rules
# because author-set attributes are stable and unambiguous.
ATTR_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("email",), "email"),
    (("tel", "phone"), "phone_e164"),
    (("given-name", "fname", "first_name", "firstname"), "full_name"),  # refined below
    (("family-name", "lname", "last_name", "lastname"), "full_name"),
    (("postal-code", "zip"), "postal_code"),
    (("address-line1", "street-address"), "address"),
    (("country",), "country"),
)

# ---------------------------------------------------------------------------
# QUESTION MAP — question substring -> literal answer (or token).
# First match wins. Mirrors worker-apply-playbook.md QUESTION MAP.
# ---------------------------------------------------------------------------

# (substrings, literal_or_token, is_token)
QUESTION_MAP: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("authorized to work", "legally authorized", "eligible to work"), "Yes", False),
    (("require sponsorship", "need sponsorship", "visa sponsorship"), "require_sponsorship", True),
    (("18 years", "over 18", "age 18", "at least 18"), "Yes", False),
    (("background check",), "Yes", False),
    (("criminal", "felony", "convicted"), "No", False),
    (("previously worked", "worked here before", "former employee"), "No", False),
    (("interviewed", "interview before", "previously interviewed", "interview with"), "No", False),
    (("how did you hear", "referral source", "source"), "Online Job Board", False),
    (("ai policy", "acknowledge", "i have read", "i agree", "i confirm", "candidate privacy", "terms"), "Yes", False),
    (("willing to relocate", "relocation", "relocate"), "Yes", False),
    (("work remotely", "comfortable remote", "remote work"), "Yes", False),
    (("gender",), "Decline to self-identify", False),
    (("race", "ethnicity"), "Decline to self-identify", False),
    (("hispanic", "latino"), "Decline to self-identify", False),
    (("veteran",), "I am not a protected veteran", False),
    (("disability",), "I do not wish to answer", False),
)

# Free-text triggers (the only place a sentence is written).
_FREE_TEXT_RE = re.compile(
    r"\b(why|tell us|cover letter|motivat|interest|describe|anything else)\b", re.I
)

# Decline-style fallbacks for selects whose exact option is missing, in order.
DECLINE_FALLBACKS: tuple[str, ...] = ("decline", "prefer not", "i don't wish", "no")


def _match_field_map(label: str, tokens: dict) -> tuple[str, str] | None:
    for substrings, target in FIELD_MAP:
        if any(sub in label for sub in substrings):
            if callable(target):
                value = target(tokens)
            else:
                value = tokens.get(target, "")
            if value:
                return value, "label"
            return None  # matched the rule but profile has no value -> escalate
    return None


def _match_attr_map(field: Field, tokens: dict) -> tuple[str, str] | None:
    blob = f"{_norm(field.autocomplete)} {_norm(field.name_attr)}"
    if not blob.strip():
        return None
    # First/last name need the split, handled explicitly.
    if any(k in blob for k in ("given-name", "fname", "first_name", "firstname")):
        v = _first_word(tokens)
        return (v, "attr") if v else None
    if any(k in blob for k in ("family-name", "lname", "last_name", "lastname")):
        v = _last_word(tokens)
        return (v, "attr") if v else None
    for keys, token_key in ATTR_MAP:
        if any(k in blob for k in keys):
            v = tokens.get(token_key, "")
            if v:
                return v, "attr"
    # type=email/tel are strong signals too.
    if field.type == "email" and tokens.get("email"):
        return tokens["email"], "attr"
    if field.type == "tel" and tokens.get("phone_e164"):
        return tokens["phone_e164"], "attr"
    return None


def _match_question_map(label: str, tokens: dict) -> tuple[str, str] | None:
    for substrings, target, is_token in QUESTION_MAP:
        if any(sub in label for sub in substrings):
            value = tokens.get(target, "") if is_token else target
            if value:
                return value, "label"
            return None
    return None


def resolve_field(field: Field, tokens: dict) -> Resolution | None:
    """Resolve one field to a Tier-0 answer, or None to escalate.

    Precedence: HTML attribute -> question map -> field map -> free-text.
    EEO/screening (question map) is checked before the identity field map so a
    'gender' <select> isn't mistaken for a name/text field.
    """
    label = _norm(field.label)

    # 1. HTML attribute signals (most reliable).
    attr = _match_attr_map(field, tokens)
    if attr:
        return Resolution(answer=attr[0], confidence=0.97, via=attr[1])

    # 2. Screening / EEO questions (yes-no, dropdown).
    q = _match_question_map(label, tokens)
    if q:
        return Resolution(answer=q[0], confidence=0.9, via=q[1])

    # 3. Identity / contact / scalar fields.
    fm = _match_field_map(label, tokens)
    if fm:
        return Resolution(answer=fm[0], confidence=0.9, via=fm[1])

    # 4. Free-text is intentionally NOT answered here. Generic boilerplate is
    #    exactly what recruiters bin, so company-specific prose ("why this
    #    role") flows to Tier 2 (Gemini) with live {company, role} context, or
    #    is left blank when optional. Tier 0 stays factual-only.
    return None


def is_free_text(field: Field) -> bool:
    """True for fields whose answer must be written prose (Tier 2 territory)."""
    return field.tag == "textarea" or bool(_FREE_TEXT_RE.search(_norm(field.label)))


def choose_select_option(answer: str, options: tuple[str, ...]) -> str | None:
    """Map a resolved answer to an available <select>/radio option.

    Match precedence is strict→loose so a country like "India" binds to "India"
    (or "India +91") and never to "British Indian Ocean Territory" just because
    that option also contains the substring "india":

      1. exact (case-insensitive)
      2. option starts with the answer  ("India +91" for "India")
      3. answer is a whole word in the option (word boundary)
      4. plain substring (last resort)
    """
    if not options:
        return answer or None
    norm_answer = _norm(answer)
    if not norm_answer:
        return None
    by_norm = {_norm(o): o for o in options}
    if norm_answer in by_norm:
        return by_norm[norm_answer]
    # Option starts with the answer (handles "India +91", "Yes - authorized").
    for opt in options:
        n = _norm(opt)
        if n.startswith(norm_answer + " ") or n.startswith(norm_answer):
            return opt
    # Answer appears as a whole word in the option.
    for opt in options:
        if re.search(rf"\b{re.escape(norm_answer)}\b", _norm(opt)):
            return opt
    # Option appears as a whole word in the answer. Handles verbose / multi-value
    # LLM replies ("English, Hindi" -> option "English"; "Yes, I am authorized"
    # -> "Yes"). Pick the first option that occurs in the answer.
    for opt in options:
        n = _norm(opt)
        if n and re.search(rf"\b{re.escape(n)}\b", norm_answer):
            return opt
    # Plain substring (last resort, weakest signal).
    for opt in options:
        if norm_answer in _norm(opt):
            return opt
    # Decline-style fallback fires ONLY when our answer is itself a decline
    # (e.g. "Decline to self-identify" worded "I prefer not to say" on the form).
    # For a non-decline answer with no match, escalate rather than guess "No".
    answer_is_decline = any(fb in norm_answer for fb in DECLINE_FALLBACKS[:-1])
    if answer_is_decline:
        for fb in DECLINE_FALLBACKS:
            for opt in options:
                if fb in _norm(opt):
                    return opt
    return None
