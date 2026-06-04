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
    is_multi: bool = False      # react-select --is-multi (select-all-that-apply)


@dataclass(frozen=True)
class Resolution:
    """A Tier-0 answer with provenance for telemetry/debugging."""

    answer: str
    confidence: float
    via: str  # 'attr' | 'label' | 'free_text'


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _norm_option(s: str | None) -> str:
    """Normalize option/answer text for loose EEO and decline matching."""
    t = _norm(s)
    return t.replace("'", "").replace("’", "")


# ---------------------------------------------------------------------------
# FIELD MAP — label substring -> token key (or a derive function)
# Ordered: first match wins. Mirrors worker-apply-playbook.md FIELD MAP.
# ---------------------------------------------------------------------------

def _first_word(tokens: dict) -> str:
    return (tokens.get("full_name") or "").split()[0] if tokens.get("full_name") else ""


def _last_word(tokens: dict) -> str:
    parts = (tokens.get("full_name") or "").split()
    return parts[-1] if len(parts) > 1 else ""


def _start_date(tokens: dict) -> str:
    """A concrete date for date-picker 'when can you start' questions.

    The profile's earliest_start_date is free text ('Immediately'), which a date
    widget rejects. Use a real near-future date the widget will accept.
    """
    return tokens.get("start_date", "")


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
    # Date-picker phrasings need a real date, not "Immediately" — checked before
    # the generic start/availability rule below.
    (
        (
            "when can you start",
            "start a new role",
            "earliest start date",
            "available start date",
            "date available",
            "available to start",
        ),
        _start_date,
    ),
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
    (("by checking this box", "i consent", "consent to", "i authorize", "i certify"), "Yes", False),
    (("willing to relocate", "relocation", "relocate"), "Yes", False),
    (("work remotely", "comfortable remote", "remote work"), "Yes", False),
    (("gender",), "gender", True),
    (("race", "ethnicity"), "race_ethnicity", True),
    (("hispanic", "latino"), "race_ethnicity", True),
    (("veteran",), "veteran_status", True),
    (("disability",), "disability_status", True),
)

# Free-text triggers (the only place a sentence is written).
_FREE_TEXT_RE = re.compile(
    r"\b(why|tell us|cover letter|motivat|interest|describe|anything else)\b", re.I
)

# Decline-style fallbacks for selects whose exact option is missing, in order.
DECLINE_FALLBACKS: tuple[str, ...] = (
    "decline",
    "prefer not",
    "do not wish",
    "don't wish",
    "wish to answer",
    "i don't wish",
    "no",
)


# "How did you hear about us?" style questions render as a required checkbox
# group (pick ≥1). They are low-stakes and have no profile-derived answer, so we
# check a single plausible option rather than escalating the whole form.
SOURCE_QUESTION_MARKERS: tuple[str, ...] = (
    "how did you hear",
    "how you heard",
    "where did you hear",
    "referral source",
    "source of your",
    "hear about us",
    "hear about this",
)
PREFERRED_SOURCE_OPTIONS: tuple[str, ...] = (
    "linkedin",
    "indeed",
    "online job board",
    "job board",
    "company website",
    "careers website",
    "company site",
    "other",
)


def is_source_question(text: str | None) -> bool:
    """True for 'how did you hear about us' style group questions."""
    blob = _norm(text)
    return any(m in blob for m in SOURCE_QUESTION_MARKERS)


def choose_checkbox_group_option(
    question: str | None, option_labels: tuple[str, ...]
) -> str | None:
    """Pick ONE option label to check for a required checkbox group.

    Only answers low-stakes source questions; returns None (escalate) for any
    other required multi-checkbox group rather than guessing a wrong answer.
    """
    if not option_labels or not is_source_question(question):
        return None
    for pref in PREFERRED_SOURCE_OPTIONS:
        for opt in option_labels:
            if pref in _norm(opt):
                return opt
    return option_labels[0]


def _is_decline_answer(answer: str) -> bool:
    n = _norm_option(answer)
    return any(fb in n for fb in DECLINE_FALLBACKS if fb != "no") or "decline" in n


def _question_context(field: Field) -> str:
    """Section + label — disability radios often label options, not the question."""
    return f"{_norm(field.section_header)} {_norm(field.label)}".strip()


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


def _workatastartup_message(field: Field, tokens: dict) -> str | None:
    """Deterministic answer for YC Work at a Startup's required Message box."""
    job_url = _norm(tokens.get("job_url"))
    label = _norm(field.label)
    if "workatastartup.com" not in job_url:
        return None
    if field.tag != "textarea" and "message" not in label:
        return None
    if "message" not in label and "cover letter" not in label:
        return None

    cover_text = str(tokens.get("cover_letter_text") or "").strip()
    if cover_text:
        return cover_text[:1800]

    name = str(tokens.get("preferred_name") or tokens.get("full_name") or "").strip()
    title = str(tokens.get("job_title") or "this role").strip()
    company = str(tokens.get("company") or "your team").strip()
    current = str(tokens.get("current_job_title") or "software engineer").strip()
    years = str(tokens.get("years_experience") or "").strip()
    exp = f" with {years} years of experience" if years else ""
    return (
        f"Hi, I'm {name}. I'm interested in the {title} role at {company}. "
        f"My background is in {current}{exp}, with hands-on work across production "
        "software, automation, and AI-enabled systems. I'd like to explore whether "
        "my experience fits what you're building."
    )


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
    q = _match_question_map(_question_context(field), tokens)
    if q:
        return Resolution(answer=q[0], confidence=0.9, via=q[1])

    # 3. Identity / contact / scalar fields.
    fm = _match_field_map(label, tokens)
    if fm:
        return Resolution(answer=fm[0], confidence=0.9, via=fm[1])

    # 4. Work at a Startup's apply form is intentionally sparse: a required
    #    "Message" textarea, and sometimes email. Fill that known field locally
    #    instead of escalating the whole application to a browser agent.
    waas_message = _workatastartup_message(field, tokens)
    if waas_message:
        return Resolution(answer=waas_message, confidence=0.86, via="label")

    # 5. Free-text is intentionally NOT answered here. Generic boilerplate is
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
    norm_answer_loose = _norm_option(answer)
    if not norm_answer:
        return None
    by_norm = {_norm(o): o for o in options}
    by_loose = {_norm_option(o): o for o in options}
    if norm_answer in by_norm:
        return by_norm[norm_answer]
    if norm_answer_loose in by_loose:
        return by_loose[norm_answer_loose]
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
    # (e.g. "I do not wish to answer" vs "I don't wish to answer" on the form).
    # For a non-decline answer with no match, escalate rather than guess "No".
    if _is_decline_answer(answer):
        for fb in DECLINE_FALLBACKS:
            for opt in options:
                if fb in _norm_option(opt):
                    return opt
    return None
