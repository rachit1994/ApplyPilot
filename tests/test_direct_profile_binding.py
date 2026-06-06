"""Tests for Resolver Tier 0 deterministic profile binding."""

from __future__ import annotations

from applypilot.apply.direct.profile_binding import (
    Field,
    choose_checkbox_group_option,
    choose_select_option,
    is_source_question,
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
    "current_company": "Happening Today",
    "current_job_title": "Senior Software Engineer",
    "years_experience": "8",
    "education_level": "Bachelors",
    "salary_number": "180000",
    "earliest_start_date": "Immediately",
    "require_sponsorship": "No",
    "address": "1 King St",
    "gender": "Male",
    "race_ethnicity": "Asian",
    "veteran_status": "I am not a protected veteran",
    "disability_status": "No, I don't have a disability",
}


def test_first_last_name_split():
    assert resolve_field(Field(label="First name"), TOKENS).answer == "Rachit"
    assert resolve_field(Field(label="Last name"), TOKENS).answer == "Srivastava"
    assert resolve_field(Field(label="Full name"), TOKENS).answer == "Rachit Srivastava"
    assert (
        resolve_field(Field(label="Legal First and Last Name"), TOKENS).answer
        == "Rachit Srivastava"
    )


def test_contact_fields():
    assert resolve_field(Field(label="Email Address"), TOKENS).answer == "rachit@example.com"
    assert resolve_field(Field(label="Mobile phone"), TOKENS).answer == "5551234567"
    assert resolve_field(Field(label="LinkedIn Profile"), TOKENS).answer.endswith("/rachit")
    assert resolve_field(Field(label="Location"), TOKENS).answer == "Toronto, ON, Canada"


def test_telephone_country_code_uses_country_not_phone():
    tokens = dict(TOKENS, country="India", phone_e164="+918168433423")
    res = resolve_field(Field(label="Telephone country code", type="select"), tokens)
    assert res is not None
    assert res.answer == "India"
    assert (
        resolve_field(Field(label="* Phone +91", type="tel"), tokens).answer
        == "+918168433423"
    )
    picked = choose_select_option("India", ("United States +1", "India\n+91", "Canada +1"))
    assert picked == "India\n+91"


def test_workable_screening_questions_resolve_tier0():
    assert (
        resolve_field(Field(label="Do you have an English CV that you can share?"), TOKENS).answer
        == "Yes"
    )
    assert resolve_field(Field(label="What is your English level?"), TOKENS).answer == "Advanced"
    assert (
        resolve_field(
            Field(label="Do you have .NET development experience of at least 5 years?"),
            TOKENS,
        ).answer
        == "Yes"
    )
    assert (
        resolve_field(
            Field(
                label=(
                    "Do you have at least two years of commercial cloud "
                    "development experience?"
                )
            ),
            TOKENS,
        ).answer
        == "Yes"
    )


def test_postal_code_attr_uses_profile_or_city_fallback():
    assert resolve_field(Field(label="Postal code", name_attr="postcode"), TOKENS).answer == "M5V"
    tokens = dict(TOKENS, city="Bengaluru", country="India", postal_code="")
    assert (
        resolve_field(Field(label="Postal code", name_attr="postcode"), tokens).answer
        == "560001"
    )


def test_attr_beats_label_ambiguity():
    # Label is bare "Name" (ambiguous) but autocomplete says it's the email.
    f = Field(label="Name", type="email", autocomplete="email")
    assert resolve_field(f, TOKENS).answer == "rachit@example.com"
    assert resolve_field(f, TOKENS).via == "attr"


def test_work_authorization_questions():
    assert resolve_field(Field(label="Are you legally authorized to work?"), TOKENS).answer == "Yes"
    assert resolve_field(Field(label="Do you require sponsorship?"), TOKENS).answer == "No"
    assert (
        resolve_field(
            Field(label="Will you now or in the future require Notion to sponsor an immigration case?"),
            TOKENS,
        ).answer
        == "No"
    )
    assert (
        resolve_field(Field(label="Yes, I am able to work from the office 3 days a week"), TOKENS).answer
        == "Yes"
    )
    assert (
        resolve_field(Field(label="Can you work from one of our offices on Anchor Days?"), TOKENS).answer
        == "Yes"
    )


def test_eeo_uses_profile_values():
    assert resolve_field(Field(label="Gender"), TOKENS).answer == "Male"
    assert resolve_field(Field(label="Race / Ethnicity"), TOKENS).answer == "Asian"
    assert "veteran" in resolve_field(Field(label="Veteran status"), TOKENS).answer.lower()
    assert (
        resolve_field(Field(label="Disability status"), TOKENS).answer
        == "No, I don't have a disability"
    )


def test_eeo_matches_section_header_when_label_is_option_text():
    f = Field(
        label="No, I don't have a disability",
        type="radio",
        section_header="Please indicate your disability status",
    )
    assert resolve_field(f, TOKENS).answer == "No, I don't have a disability"


def test_disability_answer_snaps_to_apostrophe_option():
    opts = (
        "Yes, I have a disability (or previously had a disability)",
        "No, I don't have a disability",
        "I don't wish to answer",
    )
    assert choose_select_option("No, I don't have a disability", opts) == "No, I don't have a disability"


def test_salary_and_experience():
    assert resolve_field(Field(label="Desired salary"), TOKENS).answer == "180000"
    assert resolve_field(Field(label="Years of experience"), TOKENS).answer == "8"
    assert resolve_field(Field(label="Current company"), TOKENS).answer == "Happening Today"
    assert (
        resolve_field(
            Field(label="Does this range meet your compensation requirements?"),
            TOKENS,
        ).answer
        == "Yes"
    )


def test_monthly_usd_salary_converts_from_inr_annual():
    tokens = dict(TOKENS, salary_number="5000000", salary_currency="INR")
    resolved = resolve_field(
        Field(label="What is your desired monthly base salary in USD"),
        tokens,
    )
    assert resolved is not None
    assert resolved.answer == "5000"


def test_free_text_not_answered_by_tier0():
    # Tier 0 is factual-only; free-text flows to Gemini (Tier 2) with context.
    from applypilot.apply.direct.profile_binding import is_free_text

    req = Field(label="Why do you want to work here?", tag="textarea", required=True)
    assert resolve_field(req, TOKENS) is None
    assert is_free_text(req)
    assert is_free_text(Field(label="Anything else?", tag="textarea"))
    assert not is_free_text(Field(label="Email", type="email"))


def test_workatastartup_message_answered_without_llm():
    tokens = dict(
        TOKENS,
        job_url="https://www.workatastartup.com/application?signup_job_id=123",
        cover_letter_text="I am interested in this YC startup role.",
        job_title="Founding Engineer",
        company="Acme AI",
    )
    req = Field(label="Message", tag="textarea", required=True)
    resolved = resolve_field(req, tokens)
    assert resolved is not None
    assert resolved.answer == "I am interested in this YC startup role."


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


def test_is_source_question():
    assert is_source_question("How did you hear about Twilio? *")
    assert is_source_question("Referral source")
    assert not is_source_question("Are you legally authorized to work?")
    assert not is_source_question("")


def test_checkbox_group_picks_one_source_option():
    opts = ("Careers Website", "LinkedIn", "Glassdoor", "Indeed", "Other")
    # Prefers LinkedIn (first preferred source present).
    assert choose_checkbox_group_option("How did you hear about us?", opts) == "LinkedIn"
    # No preferred match -> falls back to the first option, still one pick.
    assert choose_checkbox_group_option("How did you hear?", ("Billboard", "Radio")) == "Billboard"


def test_checkbox_group_escalates_non_source_questions():
    # A required multi-checkbox that is NOT a "how did you hear" question must
    # not be guessed — returning None escalates instead of checking a wrong box.
    assert choose_checkbox_group_option(
        "Which certifications do you hold?", ("AWS", "GCP", "Azure")
    ) is None
    assert choose_checkbox_group_option("", ("A", "B")) is None


def test_checkbox_group_handles_export_control_none_of_above():
    opts = (
        "Citizen or permanent resident of Cuba, Iran, North Korea, or Syria",
        "Ordinarily a resident of Russia or Belarus and not willing to relocate",
        "None of the above",
    )
    assert (
        choose_checkbox_group_option(
            "Please confirm whether any of the below applies to you. Select all that apply.",
            opts,
        )
        == "None of the above"
    )


def test_checkbox_group_handles_export_control_followup_not_applicable():
    opts = (
        "U.S. citizen",
        "Individual granted permanent residency in a country other than Cuba, Iran, North Korea, or Syria",
        "None of these apply to me",
        "Not applicable (i.e., I selected none of the above for the prior question)",
    )
    assert choose_checkbox_group_option(
        "If you selected a response to the prior question other than none of the above, select all that apply.",
        opts,
    ).startswith("Not applicable")


def test_date_picker_start_question_uses_concrete_date():
    # "When can you start a new role?" is a date picker — must get a real date
    # (the start_date token), not the free-text "Immediately".
    tokens = dict(TOKENS, start_date="06/18/2026", earliest_start_date="Immediately")
    assert resolve_field(Field(label="When can you start a new role?"), tokens).answer == "06/18/2026"
    assert resolve_field(Field(label="Earliest start date"), tokens).answer == "06/18/2026"
    # A generic "notice period" still uses the free-text availability.
    assert resolve_field(Field(label="Notice period"), tokens).answer == "Immediately"


def test_workable_skill_requirement_radiogroup_resolves_yes():
    field = Field(
        label="Experience: Minimum of 3 years building production systems",
        tag="fieldset",
        options=("Yes", "No"),
    )
    res = resolve_field(field, TOKENS)
    assert res is not None
    assert res.answer == "Yes"
    assert res.via == "label"


def test_workable_europe_location_trap_does_not_auto_yes():
    field = Field(
        label="Location: Must be physically located and working within Europe",
        section_header="Requirements",
        tag="fieldset",
        options=("Yes", "No"),
    )
    assert resolve_field(field, TOKENS) is None


def test_remaining_gaps_are_location_traps_only():
    from applypilot.apply.direct.profile_binding import remaining_gaps_are_location_traps

    traps = [
        Field(label="Location: Must be physically located within Europe", options=("Yes", "No")),
    ]
    mixed = traps + [Field(label="Experience: 5 years Python", options=("Yes", "No"))]
    assert remaining_gaps_are_location_traps(traps)
    assert not remaining_gaps_are_location_traps(mixed)
