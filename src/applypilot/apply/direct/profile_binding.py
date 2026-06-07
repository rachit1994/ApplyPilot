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


def _notice_period(_label: str, tokens: dict) -> str:
    """Workable notice-period widgets accept day counts, not free text."""
    raw = str(tokens.get("earliest_start_date") or "Immediately").strip().lower()
    if raw in {"immediately", "immediate", "now", "asap", "0 days", "0 day"}:
        return "0"
    match = re.search(r"(\d+)", raw)
    if match:
        return match.group(1)
    if "week" in raw:
        return "15"
    if "month" in raw:
        return "30"
    return "15"


def _years_numeric(tokens: dict) -> str:
    """Strip non-digits from years_experience for <input type=number> widgets."""
    raw = str(tokens.get("years_experience") or "").strip()
    match = re.search(r"(\d+)", raw)
    return match.group(1) if match else raw


def _hours_per_week(_label: str, tokens: dict) -> str:
    """Micro1/contractor forms ask weekly availability as a number."""
    explicit = str(tokens.get("hours_per_week") or "").strip()
    match = re.search(r"(\d+)", explicit)
    if match:
        return match.group(1)
    full_time = str(tokens.get("available_for_full_time") or "Yes").strip().lower()
    if full_time in {"yes", "true", "1", "full-time", "full time"}:
        return "40"
    return "20"

def _location(tokens: dict) -> str:
    parts = [
        tokens.get("city", ""),
        tokens.get("province_state", ""),
        tokens.get("country", ""),
    ]
    return ", ".join(str(p).strip() for p in parts if str(p).strip())


def _postal_code(tokens: dict) -> str:
    explicit = str(tokens.get("postal_code") or "").strip()
    if explicit:
        return explicit
    city = _norm(tokens.get("city"))
    country = _norm(tokens.get("country"))
    if city in {"bengaluru", "bangalore"} and country == "india":
        return "560001"
    return ""


def _salary_for_label(label: str, tokens: dict) -> str:
    raw = str(tokens.get("salary_number") or "").strip()
    if not raw:
        return ""
    try:
        annual = float(re.sub(r"[^0-9.]+", "", raw))
    except ValueError:
        return raw
    if annual <= 0:
        return raw

    currency = _norm(tokens.get("salary_currency") or "USD")
    value = annual
    if "usd" in label and currency in {"inr", "rs", "rupee", "rupees"}:
        # Keep this conservative and deterministic. Forms need a practical
        # number; profile currency remains the source of truth for local roles.
        value = annual / 83.0
    if any(marker in label for marker in ("monthly", "per month", "/ month")):
        value /= 12.0
    if any(
        marker in label
        for marker in ("hourly", "per hour", "/ hour", "hr rate", "rate in usd")
    ):
        value /= 2080.0
    return str(int(round(value / 100.0) * 100 if value >= 1000 else round(value)))


_COUNTRY_PHONE_CODE_MARKERS = (
    "telephone country code",
    "phone country code",
    "country phone code",
    "country calling code",
    "calling code",
)


def _is_country_phone_code_label(label: str) -> bool:
    return any(m in label for m in _COUNTRY_PHONE_CODE_MARKERS)


def _phone_local_answer(label: str, tokens: dict) -> str:
    if _is_country_phone_code_label(label) or "extension" in label:
        return ""
    return str(tokens.get("phone_national") or tokens.get("phone_digits") or "").strip()


# Each rule: (list of label substrings, token_key OR callable(tokens)->str)
FIELD_MAP: tuple[tuple[tuple[str, ...], object], ...] = (
    (("first and last name", "first & last name"), "full_name"),
    (("first name",), _first_word),
    (("last name", "surname", "family name"), _last_word),
    (("full name", "your name", "legal name"), "full_name"),
    (("preferred name",), "preferred_name"),
    (("email",), "email"),
    # Workable (and similar) split phone into country-code combobox + local number.
    # Must precede the generic phone rule — "telephone" alone would bind phone_e164.
    (
        ("telephone country code", "phone country code", "country phone code", "country calling code", "calling code"),
        "country",
    ),
    (("phone number", "mobile number"), "phone_national"),
    (("phone device type", "device type"), lambda _l, _t: "Mobile"),
    (("phone", "mobile", "telephone"), "phone_e164"),
    (("location",), _location),
    (("address", "street"), "address"),
    (("city", "town"), "city"),
    (("state", "province"), "province_state"),
    (("country",), "country"),
    (("zip", "postal", "postcode"), _postal_code),
    (("linkedin",), "linkedin_url"),
    (("github",), "github_url"),
    (("portfolio", "website", "personal site"), "portfolio_url"),
    (("current company", "current employer"), "current_company"),
    (("current title", "current job title", "most recent title"), "current_job_title"),
    (
        (
            "years of experience",
            "years experience",
            "overall engineering experience",
            "engineering experience",
        ),
        _years_numeric,
    ),
    (
        ("how soon can you start", "start the work"),
        _notice_period,
    ),
    (("hours per week", "hours/week", "hours a week", "weekly hours"), _hours_per_week),
    (("education", "degree", "highest level"), "education_level"),
    (
        ("salary", "compensation", "expected pay", "desired salary", "ctc", "hourly rate"),
        _salary_for_label,
    ),
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
    (("start date", "available"), "earliest_start_date"),
    (("notice period", "notice priod"), _notice_period),
)

# HTML autocomplete / name attribute -> token key. Checked BEFORE label rules
# because author-set attributes are stable and unambiguous.
ATTR_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("email",), "email"),
    (("tel", "phone"), "phone_e164"),
    (("given-name", "fname", "first_name", "firstname"), "full_name"),  # refined below
    (("family-name", "lname", "last_name", "lastname"), "full_name"),
    (("postal-code", "postcode", "postal", "zip"), "postal_code"),
    (("address-line1", "street-address"), "address"),
    (("city",), "city"),
    (("country",), "country"),
)

# ---------------------------------------------------------------------------
# QUESTION MAP — question substring -> literal answer (or token).
# First match wins. Mirrors worker-apply-playbook.md QUESTION MAP.
# ---------------------------------------------------------------------------

# (substrings, literal_or_token, is_token)
QUESTION_MAP: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("only for us based positions", "roles posted in the us only"), "Not applicable", False),
    (("does this range meet your compensation", "meet your compensation requirements"), "Yes", False),
    (("authorized to work", "legally authorized", "eligible to work", "legal authorization to work"), "Yes", False),
    (
        (
            "minimum education",
            "education requirement",
            "bachelor's degree",
            "bachelor degree",
            "fulfill our minimum education",
        ),
        "Yes",
        False,
    ),
    (
        (
            "require sponsorship",
            "need sponsorship",
            "visa sponsorship",
            "sponsor an immigration",
            "sponsor immigration",
            "immigration case",
            "obtain, renew, extend or transfer a visa",
            "work permit in order to commence",
            "need support in obtaining a work visa",
        ),
        "require_sponsorship",
        True,
    ),
    (
        (
            "personal relationship",
            "relationship with a current",
            "contingent worker",
            "family relationship includes",
        ),
        "No",
        False,
    ),
    (("18 years", "over 18", "age 18", "at least 18"), "Yes", False),
    (("background check",), "Yes", False),
    (("criminal", "felony", "convicted"), "No", False),
    (("previously worked", "worked here before", "former employee"), "No", False),
    (("interviewed", "interview before", "previously interviewed", "interview with"), "No", False),
    (("how did you hear", "referral source", "hear about us", "hear about this"), "LinkedIn", False),
    (("ai policy", "acknowledge", "i have read", "i agree", "i confirm", "candidate privacy", "terms"), "Yes", False),
    (("by checking this box", "i consent", "consent to", "i authorize", "i certify"), "Yes", False),
    (("based in india", "currently based in india"), "Yes", False),
    (("remote role", "auto renewing", "deel", "direct contract"), "Yes", False),
    (("willing to relocate", "relocation", "relocate"), "Yes", False),
    (
        (
            "hybrid",
            "work from the office",
            "in person",
            "in-office",
            "anchor days",
            "working from one of our offices",
        ),
        "Yes",
        False,
    ),
    (("work remotely", "comfortable remote", "remote work"), "Yes", False),
    (("english cv", "english resume that you can share"), "Yes", False),
    (("english level", "level of english", "proficiency in english"), "Advanced", False),
    ((".net development", "dotnet development experience"), "Yes", False),
    (
        ("commercial cloud development", "cloud development experience of at least"),
        "Yes",
        False,
    ),
    (("gender",), "gender", True),
    (("race", "ethnicity"), "race_ethnicity", True),
    (("hispanic", "latino"), "race_ethnicity", True),
    (("veteran",), "veteran_status", True),
    (("disability",), "disability_status", True),
    (("citizen of another country", "permanent residency status"), "No", False),
    (("additional nationalities", "confirm them"), "Not applicable", False),
    (
        (
            "direct reports",
            "team members you",
            "team size",
            "people you manage",
        ),
        "Not in my current role; prior experience leading squads of 4–6 engineers.",
        False,
    ),
    (
        (
            "hiring, performance reviews",
            "performance reviews, or mentoring",
            "mentoring within your team",
            "involved in hiring",
        ),
        "Yes — hiring, performance reviews, and mentoring.",
        False,
    ),
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

EXPORT_CONTROL_QUESTION_MARKERS: tuple[str, ...] = (
    "cuba",
    "iran",
    "north korea",
    "syria",
    "crimea",
    "donetsk",
    "luhansk",
    "zaporizhzhia",
    "kherson",
    "russia",
    "belarus",
)
EXPORT_CONTROL_FOLLOWUP_MARKERS: tuple[str, ...] = (
    "prior question",
    "previous question",
    "selected a response",
    "other than",
)
EXPORT_CONTROL_NONE_OPTIONS: tuple[str, ...] = (
    "none of the above",
    "none of these apply",
    "none apply",
)
EXPORT_CONTROL_NOT_APPLICABLE_OPTIONS: tuple[str, ...] = (
    "not applicable",
    "n/a",
)


def is_source_question(text: str | None) -> bool:
    """True for 'how did you hear about us' style group questions."""
    blob = _norm(text)
    return any(m in blob for m in SOURCE_QUESTION_MARKERS)


def _pick_option_containing(
    option_labels: tuple[str, ...],
    needles: tuple[str, ...],
) -> str | None:
    for needle in needles:
        for opt in option_labels:
            if needle in _norm(opt):
                return opt
    return None


def _pick_export_control_option(
    question: str | None,
    option_labels: tuple[str, ...],
) -> str | None:
    """Answer explicit sanctions/export-control checkbox groups conservatively.

    These groups are phrased as "select all that apply" and include their own
    negative / not-applicable option. Only answer when the form text contains
    high-confidence restricted-country markers or a follow-up to that question.
    """
    blob = " ".join((_norm(question), *(_norm(opt) for opt in option_labels)))
    has_restricted_country_marker = any(
        marker in blob for marker in EXPORT_CONTROL_QUESTION_MARKERS
    )
    if has_restricted_country_marker:
        return _pick_option_containing(option_labels, EXPORT_CONTROL_NONE_OPTIONS)

    is_followup = any(marker in blob for marker in EXPORT_CONTROL_FOLLOWUP_MARKERS)
    if is_followup:
        return _pick_option_containing(
            option_labels, EXPORT_CONTROL_NOT_APPLICABLE_OPTIONS
        ) or _pick_option_containing(option_labels, EXPORT_CONTROL_NONE_OPTIONS)

    return None


_TECHNOLOGY_QUESTION_MARKERS = (
    "select all the technologies",
    "technologies you are",
    "technology you are",
    "tech stack",
    "select all skills",
    "hands on experience with",
    "hands-on experience with",
    "front-end framework",
    "frontend framework",
    "front end framework",
    "frameworks have you worked",
    "which technologies",
    "programming languages",
    "languages have you worked",
)

_TECHNOLOGY_KEYWORDS = (
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "vue",
    "angular",
    "node",
    "aws",
    "gcp",
    "azure",
    "kubernetes",
    "docker",
    "sql",
    "postgres",
    "mongodb",
    "redis",
    "go",
    "golang",
    "rust",
    "scala",
    "kafka",
    "spark",
    "terraform",
    "linux",
    "git",
    "api",
    "microservice",
    "devops",
    "cloud",
    "backend",
    "frontend",
    "full stack",
    "full-stack",
    ".net",
    "dotnet",
    "c++",
    "spring",
    "django",
    "flask",
    "fastapi",
    "graphql",
    "rest",
)


def is_technology_multi_checkbox_question(question: str | None) -> bool:
    """True for Lever-style 'select all technologies' checkbox groups."""
    q = _norm(question)
    if not q:
        return False
    return any(marker in q for marker in _TECHNOLOGY_QUESTION_MARKERS)


def technology_checkbox_picks(option_labels: tuple[str, ...]) -> tuple[str, ...]:
    """Labels to check for a required multi-select technology group."""
    if not option_labels:
        return ()
    skip = {"none", "other", "n/a", "not applicable"}
    picks: list[str] = []
    for opt in option_labels:
        lo = _norm(opt)
        if not lo or lo in skip:
            continue
        if any(kw in lo for kw in _TECHNOLOGY_KEYWORDS):
            picks.append(opt)
    if picks:
        return tuple(picks)
    broad = tuple(
        opt
        for opt in option_labels
        if _norm(opt) not in skip
    )
    return broad[: min(8, len(broad))]


def choose_checkbox_group_option(
    question: str | None, option_labels: tuple[str, ...]
) -> str | None:
    """Pick ONE option label to check for a required checkbox group.

    Only answers low-stakes source questions and explicit export-control groups
    that provide a negative/not-applicable option. Everything else escalates
    rather than guessing a wrong answer.
    """
    if not option_labels:
        return None
    export_pick = _pick_export_control_option(question, option_labels)
    if export_pick:
        return export_pick
    if not is_source_question(question):
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
    if "extension" in label:
        return None
    for substrings, target in FIELD_MAP:
        if any(sub in label for sub in substrings):
            if callable(target):
                try:
                    value = target(label, tokens)
                except TypeError:
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
    if any(k in blob for k in ("postal-code", "postcode", "postal", "zip")):
        v = _postal_code(tokens)
        return (v, "attr") if v else None
    for keys, token_key in ATTR_MAP:
        if any(k in blob for k in keys):
            v = tokens.get(token_key, "")
            if v:
                return v, "attr"
    # type=email/tel are strong signals too.
    if field.type == "email" and tokens.get("email"):
        return tokens["email"], "attr"
    label = _norm(field.label)
    if _is_country_phone_code_label(label) or "phone extension" in label:
        return None
    if field.type == "tel" and tokens.get("phone_e164"):
        if "phone number" in label or "mobile" in label:
            local = str(tokens.get("phone_national") or tokens.get("phone_digits") or "").strip()
            return (local, "attr") if local else None
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


_YES_NO_OPTIONS = frozenset({"yes", "no"})

LOCATION_REQUIREMENT_MARKERS = (
    "physically located",
    "located and working within",
    "within europe",
    "must be in europe",
    "european union",
    "located in the united states",
    "must be based in the us",
    "based in the us",
    "us time zone",
    "legally authorized to work in the us",
    "authorized to work in the us",
    "based in the uk",
    "within the uk",
)

SKILL_REQUIREMENT_MARKERS = (
    "experience:",
    "minimum of",
    "proficiency in",
    "strong understanding",
    "excellent communication",
    "proven experience",
    "demonstrated",
    "years of experience",
    "technical skills",
    "cloud platforms",
    "python",
    " sql",
    "data analysis",
    "bi tools",
    "client-facing",
    "communication skills",
    "requirements:",
    "ability to",
)


def is_yes_no_radiogroup(field: Field) -> bool:
    if not field.options:
        return False
    opts = {_norm(o) for o in field.options}
    return opts <= _YES_NO_OPTIONS


def is_yes_no_select_options(options: tuple[str, ...]) -> bool:
    """True when a <select> only offers screening-style Yes/No choices."""
    if not options:
        return False
    normalized = {_norm_option(o) for o in options if _norm_option(o)}
    normalized = {o for o in normalized if o not in {"select", "select..."}}
    return bool(normalized) and normalized <= _YES_NO_OPTIONS


def is_phantom_technology_select(field: Field) -> bool:
    """Lever mis-labels some Yes/No card selects with a technology question."""
    if field.tag != "select" and field.type not in {"select-one", "select"}:
        return False
    if not is_technology_multi_checkbox_question(field.label):
        return False
    return is_yes_no_select_options(field.options)


def is_location_requirement_trap(label: str) -> bool:
    blob = _norm(label)
    return any(marker in blob for marker in LOCATION_REQUIREMENT_MARKERS)


def remaining_gaps_are_location_traps(fields: list[Field]) -> bool:
    if not fields:
        return False
    return all(
        is_location_requirement_trap(f"{f.section_header} {f.label}".strip())
        for f in fields
    )


def _workable_self_assessment(field: Field, tokens: dict) -> Resolution | None:
    """Workable requirement fieldsets: Yes/No self-assessment per requirement."""
    if not is_yes_no_radiogroup(field):
        return None
    context = _question_context(field)
    if any(marker in context for marker in SKILL_REQUIREMENT_MARKERS):
        pick = choose_select_option("Yes", field.options)
        if pick:
            return Resolution(answer=pick, confidence=0.88, via="label")
    if len(context) > 40:
        pick = choose_select_option("Yes", field.options)
        if pick:
            return Resolution(answer=pick, confidence=0.75, via="label")
    return None


def _sponsorship_details_field(field: Field, tokens: dict) -> Resolution | None:
    """Visa/sponsorship follow-up textareas ('Please provide details')."""
    label = _norm(field.label)
    if "provide detail" not in label and "please provide" not in label:
        return None
    ctx = _question_context(field)
    visa_ctx = any(
        marker in ctx
        for marker in (
            "visa",
            "sponsor",
            "work permit",
            "immigration",
            "authorization",
            "permit",
        )
    )
    needs_sponsor = str(tokens.get("require_sponsorship") or "").strip().lower() in {
        "yes",
        "true",
        "y",
    }
    if not visa_ctx and not needs_sponsor:
        return None
    detail = str(tokens.get("sponsorship_details") or "").strip()
    if not detail:
        permit = str(tokens.get("work_permit_type") or "").strip()
        if needs_sponsor:
            detail = (
                "I will require employer sponsorship for work authorization to commence employment."
                + (f" Current permit/status: {permit}." if permit else "")
            )
    if detail:
        return Resolution(answer=detail, confidence=0.88, via="label")
    return None


def _default_prose_message(tokens: dict) -> str:
    """Short role-specific message when no cover letter text is available."""
    name = str(tokens.get("preferred_name") or tokens.get("full_name") or "").strip()
    title = str(tokens.get("job_title") or tokens.get("current_job_title") or "this role").strip()
    company = str(tokens.get("company") or "your team").strip()
    current = str(tokens.get("current_job_title") or "software engineer").strip()
    years = str(tokens.get("years_experience") or "").strip()
    exp = f" with {years} years of experience" if years else ""
    opener = f"Hi, I'm {name}. " if name else ""
    return (
        f"{opener}I'm interested in the {title} role at {company}. "
        f"My background is in {current}{exp}, with hands-on work across production "
        "software, automation, and AI-enabled systems. I'd like to explore whether "
        "my experience fits what you're building."
    )


def _prose_application_message(field: Field, tokens: dict) -> Resolution | None:
    """Tier-0 answers for cover-letter / why-us / additional-info textareas."""
    label = _norm(field.label)
    is_prose = field.tag == "textarea" or bool(_FREE_TEXT_RE.search(field.label or ""))
    if not is_prose:
        return None
    if field.type in {"file", "hidden", "submit", "button"}:
        return None

    cover_text = str(tokens.get("cover_letter_text") or "").strip()
    if cover_text:
        return Resolution(answer=cover_text[:4000], confidence=0.9, via="cover_letter")

    return Resolution(answer=_default_prose_message(tokens)[:4000], confidence=0.82, via="prose_default")


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

    return _default_prose_message(tokens)


def resolve_field(field: Field, tokens: dict) -> Resolution | None:
    """Resolve one field to a Tier-0 answer, or None to escalate.

    Precedence: HTML attribute -> question map -> field map -> free-text.
    EEO/screening (question map) is checked before the identity field map so a
    'gender' <select> isn't mistaken for a name/text field.
    """
    label = _norm(field.label)

    if "extension" in label and "phone" in label:
        return None

    # Country-code search widgets share type=tel with the local number field.
    if _is_country_phone_code_label(label):
        fm = _match_field_map(label, tokens)
        if fm:
            return Resolution(answer=fm[0], confidence=0.95, via=fm[1])
        return None

    if "phone number" in label or (
        "mobile" in label and "country" not in label and "extension" not in label
    ):
        local = str(tokens.get("phone_national") or tokens.get("phone_digits") or "").strip()
        if local:
            return Resolution(answer=local, confidence=0.95, via="label")

    # 1. HTML attribute signals (most reliable).
    attr = _match_attr_map(field, tokens)
    if attr:
        return Resolution(answer=attr[0], confidence=0.97, via=attr[1])

    sponsor_detail = _sponsorship_details_field(field, tokens)
    if sponsor_detail:
        return sponsor_detail

    # 2. Screening / EEO questions (yes-no, dropdown).
    q = _match_question_map(_question_context(field), tokens)
    if q:
        return Resolution(answer=q[0], confidence=0.9, via=q[1])

    # 2b. Workable per-requirement Yes/No radiogroups — before field map so a
    #     "Location: … within Europe" requirement is not mistaken for address.
    if is_yes_no_radiogroup(field):
        context = _question_context(field)
        if is_location_requirement_trap(context):
            return None
        wa_req = _workable_self_assessment(field, tokens)
        if wa_req:
            return wa_req

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

    prose = _prose_application_message(field, tokens)
    if prose:
        return prose

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
    if "veteran" in norm_answer and "not" in norm_answer:
        for opt in options:
            n = _norm(opt)
            if "veteran" in n and "not" in n:
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
