"""Workday adapter — *.myworkdayjobs.com multi-step application FSM.

Workday career sites use a linear wizard: sign-in (when needed), My Information,
My Experience, Voluntary Disclosures, Review, then Submit. Account creation is
out of scope — a persistent logged-in worker profile is required; a login wall
without session returns ``awaiting_login``.
"""

from __future__ import annotations

from applypilot.apply.direct.adapters.base import Adapter

ADAPTER = Adapter(
    family="workday",
    apply_button_texts=("apply", "apply now", "apply manually"),
    submit_button_texts=("submit", "submit application"),
    success_markers=(
        "thank you for applying",
        "application has been submitted",
        "your application was submitted",
        "successfully submitted",
        "we received your application",
    ),
    expired_markers=(
        "no longer accepting applications",
        "position has been filled",
        "job posting is no longer available",
        "page not found",
        "404",
    ),
)

# FSM states in wizard order (happy path).
FSM_STATES: tuple[str, ...] = (
    "account_or_signin",
    "my_information",
    "my_experience",
    "voluntary_disclosures",
    "review",
    "submit",
)

# (state, body-text / DOM markers) — checked in reverse wizard order so later
# steps win when multiple headings appear in chrome/footer text.
_STATE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "submit",
        (
            "data-automation-id=\"submitButton\"",
            "data-automation-id='submitbutton'",
            "submit application",
        ),
    ),
    (
        "review",
        (
            "data-automation-id=\"reviewPage\"",
            "review and submit",
            "review your application",
            "review application",
        ),
    ),
    (
        "voluntary_disclosures",
        (
            "data-automation-id=\"voluntaryDisclosuresPage\"",
            "voluntary disclosures",
            "voluntary self-identification",
        ),
    ),
    (
        "my_experience",
        (
            "data-automation-id=\"experiencePage\"",
            "my experience",
            "work experience",
        ),
    ),
    (
        "my_information",
        (
            "data-automation-id=\"personalInfoPage\"",
            "my information",
            "personal information",
        ),
    ),
    (
        "account_or_signin",
        (
            "data-automation-id=\"signInContent\"",
            "data-automation-id=\"createAccountLink\"",
            "sign in to apply",
            "create account",
            "sign in with email",
        ),
    ),
)

_TRANSITIONS: dict[str, tuple[str, str]] = {
    "account_or_signin": ("my_information", "next_page"),
    "my_information": ("my_experience", "next_page"),
    "my_experience": ("voluntary_disclosures", "next_page"),
    "voluntary_disclosures": ("review", "next_page"),
    "review": ("submit", "submit"),
    "submit": ("submit", "submit"),
}

_LOGIN_WALL_MARKERS: tuple[str, ...] = (
    "sign in to apply",
    "create account",
    "sign in with email",
    "data-automation-id=\"signInContent\"",
    "data-automation-id=\"createAccountLink\"",
    "type=\"password\"",
)


def _normalize(html_or_text: str) -> str:
    return " ".join(html_or_text.lower().split())


def is_login_wall(html_or_text: str) -> bool:
    """True when the page shows Workday sign-in / account creation chrome."""
    text = _normalize(html_or_text)
    return any(marker in text for marker in _LOGIN_WALL_MARKERS)


def detect_workday_state(html_or_text: str) -> str | None:
    """Return the FSM state implied by Workday page markers, or None if unknown."""
    text = _normalize(html_or_text)
    if not text:
        return None
    if any(marker in text for marker in ADAPTER.success_markers):
        return None
    for state, markers in _STATE_MARKERS:
        if any(marker in text for marker in markers):
            return state
    return None


def workday_next_action(state: str, *, has_session: bool = False) -> str:
    """Return the executor action for *state* (fill, next_page, submit, awaiting_login)."""
    if state == "account_or_signin":
        return "next_page" if has_session else "awaiting_login"
    if state in ("my_information", "my_experience", "voluntary_disclosures"):
        return "fill"
    if state in ("review", "submit"):
        return "submit"
    raise ValueError(f"unknown workday FSM state: {state!r}")


def workday_transition(state: str) -> tuple[str, str]:
    """Return ``(next_state, action)`` after completing *state* on the happy path."""
    try:
        return _TRANSITIONS[state]
    except KeyError as exc:
        raise ValueError(f"unknown workday FSM state: {state!r}") from exc
