"""Unit tests for the Workday FSM adapter (state detection + transitions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.apply.direct.adapters import get_adapter
from applypilot.apply.direct.adapters import workday as wd

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture", "expected_state"),
    [
        ("workday_account_signin.html", "account_or_signin"),
        ("workday_my_information.html", "my_information"),
        ("workday_my_experience.html", "my_experience"),
        ("workday_voluntary_disclosures.html", "voluntary_disclosures"),
        ("workday_review.html", "review"),
        ("workday_submit.html", "submit"),
    ],
)
def test_detect_workday_state_from_fixtures(fixture: str, expected_state: str):
    html = _load(fixture)
    assert wd.detect_workday_state(html) == expected_state


@pytest.mark.parametrize(
    ("state", "expected_action"),
    [
        ("my_information", "fill"),
        ("my_experience", "fill"),
        ("voluntary_disclosures", "fill"),
        ("review", "submit"),
        ("submit", "submit"),
    ],
)
def test_workday_next_action_fill_and_submit_states(state: str, expected_action: str):
    assert wd.workday_next_action(state) == expected_action


def test_workday_next_action_signin_without_session():
    assert wd.workday_next_action("account_or_signin") == "awaiting_login"


def test_workday_next_action_signin_with_session():
    assert wd.workday_next_action("account_or_signin", has_session=True) == "next_page"


def test_workday_next_action_unknown_state():
    with pytest.raises(ValueError, match="unknown workday FSM state"):
        wd.workday_next_action("not_a_state")


@pytest.mark.parametrize(
    ("state", "next_state", "action"),
    [
        ("account_or_signin", "my_information", "next_page"),
        ("my_information", "my_experience", "next_page"),
        ("my_experience", "voluntary_disclosures", "next_page"),
        ("voluntary_disclosures", "review", "next_page"),
        ("review", "submit", "submit"),
        ("submit", "submit", "submit"),
    ],
)
def test_workday_transition_table(state: str, next_state: str, action: str):
    assert wd.workday_transition(state) == (next_state, action)


def test_workday_transition_unknown_state():
    with pytest.raises(ValueError, match="unknown workday FSM state"):
        wd.workday_transition("bogus")


def test_login_wall_fixture():
    html = _load("workday_account_signin.html")
    assert wd.is_login_wall(html)
    assert wd.workday_next_action(wd.detect_workday_state(html)) == "awaiting_login"


def test_unauthenticated_apply_gate_accenture_style():
    html = (
        "<html><body>"
        "<button>Sign In</button>"
        "<button>Apply manually</button>"
        "<span>Autofill with Resume</span>"
        "</body></html>"
    )
    url = (
        "https://accenture.wd103.myworkdayjobs.com/AccentureCareers/job/"
        "Bengaluru/Solution-Architect_ATCI-5479571-S1999861-1/apply"
    )
    assert not wd.is_login_wall(html)
    assert wd.is_unauthenticated_apply_gate(html, page_url=url)


def test_success_page_returns_no_fsm_state():
    html = "<html><body>Thank you for applying. Your application has been submitted.</body></html>"
    assert wd.detect_workday_state(html) is None


def test_adapter_registered():
    adapter = get_adapter("workday")
    assert adapter is not None
    assert adapter.family == "workday"
    assert "apply" in adapter.apply_button_texts[0]
