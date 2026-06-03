"""Tests for Resolver Tier 0 deterministic profile binding."""

from __future__ import annotations

from applypilot.apply.direct.profile_binding import (
    Field,
    choose_select_option,
    resolve_field,
)

TOKENS = {
    "full_name": "Rachit Srivastava",
    "preferred_name": "Rachit",
    "email": "rachit@example.com",
    "phone_digits": "5551234567",
    "phone_e164": "5551234567",
    "city": "Toronto",
    "province_state": "ON",
    "country": "Canada",
    "postal_code": "M5V",
    "linkedin_url": "https://linkedin.com/in/rachit",
    "github_url": "https://github.com/rachit",
    "portfolio_url": "https://rachit.dev",
    "current_job_title": "Senior Software Engineer",
    "years_experience": "8",
    "education_level": "Bachelors",
    "salary_number": "180000",
    "earliest_start_date": "Immediately",
    "require_sponsorship": "No",
    "address": "1 King St",
}


def test_first_last_name_split():
    assert resolve_field(Field(label="First name"), TOKENS).answer == "Rachit"
    assert resolve_field(Field(label="Last name"), TOKENS).answer == "Srivastava"
    assert resolve_field(Field(label="Full name"), TOKENS).answer == "Rachit Srivastava"


def test_contact_fields():
    assert resolve_field(Field(label="Email Address"), TOKENS).answer == "rachit@example.com"
    assert resolve_field(Field(label="Mobile phone"), TOKENS).answer == "5551234567"
    assert resolve_field(Field(label="LinkedIn Profile"), TOKENS).answer.endswith("/rachit")


def test_attr_beats_label_ambiguity():
    # Label is bare "Name" (ambiguous) but autocomplete says it's the email.
    f = Field(label="Name", type="email", autocomplete="email")
    assert resolve_field(f, TOKENS).answer == "rachit@example.com"
    assert resolve_field(f, TOKENS).via == "attr"


def test_work_authorization_questions():
    assert resolve_field(Field(label="Are you legally authorized to work?"), TOKENS).answer == "Yes"
    assert resolve_field(Field(label="Do you require sponsorship?"), TOKENS).answer == "No"


def test_eeo_defaults_to_decline():
    assert resolve_field(Field(label="Gender"), TOKENS).answer == "Decline to self-identify"
    assert resolve_field(Field(label="Race / Ethnicity"), TOKENS).answer == "Decline to self-identify"
    assert "veteran" in resolve_field(Field(label="Veteran status"), TOKENS).answer.lower()


def test_salary_and_experience():
    assert resolve_field(Field(label="Desired salary"), TOKENS).answer == "180000"
    assert resolve_field(Field(label="Years of experience"), TOKENS).answer == "8"


def test_free_text_not_answered_by_tier0():
    # Tier 0 is factual-only; free-text flows to Gemini (Tier 2) with context.
    from applypilot.apply.direct.profile_binding import is_free_text

    req = Field(label="Why do you want to work here?", tag="textarea", required=True)
    assert resolve_field(req, TOKENS) is None
    assert is_free_text(req)
    assert is_free_text(Field(label="Anything else?", tag="textarea"))
    assert not is_free_text(Field(label="Email", type="email"))


def test_unknown_field_escalates():
    assert resolve_field(Field(label="What is your favorite color?"), TOKENS) is None


def test_matched_rule_but_empty_token_escalates():
    # "github" matches the field map, but if the token is empty we escalate
    # rather than fill blank.
    tokens = dict(TOKENS, github_url="")
    assert resolve_field(Field(label="GitHub URL"), tokens) is None


def test_choose_select_option_exact_and_fallback():
    opts = ("Yes", "No", "Decline to self-identify")
    assert choose_select_option("Yes", opts) == "Yes"
    # A decline answer maps to a differently-worded decline option.
    assert (
        choose_select_option("Decline to self-identify", ("Yes", "No", "I prefer not to say"))
        == "I prefer not to say"
    )
    # Substring match.
    assert choose_select_option("decline", ("I decline to answer",)) == "I decline to answer"
    # A non-decline answer with no matching option escalates (never guesses "No").
    assert choose_select_option("Maybe", ("Yes", "No")) is None
    assert choose_select_option("Two-Spirit", ("Male", "Female")) is None
