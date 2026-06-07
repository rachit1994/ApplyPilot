"""Tests for the Direct Apply engine: dispatch, settings, throttle, driver gates."""

from __future__ import annotations

import importlib

import pytest

from applypilot.apply import apply_settings
from applypilot.apply.direct import driver, throttle
from applypilot.apply.direct.adapters import get_adapter


# --------------------------------------------------------------------------- #
# Adapter dispatch
# --------------------------------------------------------------------------- #

def test_greenhouse_adapter_dispatched(no_skip_ats):
    adapter = get_adapter("greenhouse")
    assert adapter is not None
    assert adapter.family == "greenhouse"
    assert adapter.submit_button_texts


@pytest.mark.parametrize("family", ["lever", "ashby"])
def test_lever_ashby_adapter_dispatched(family, no_skip_ats):
    adapter = get_adapter(family)
    assert adapter is not None
    assert adapter.family == family


@pytest.mark.parametrize("family", ["workday"])
def test_workday_adapter_dispatched(family, no_skip_ats):
    adapter = get_adapter(family)
    assert adapter is not None
    assert adapter.family == family


@pytest.mark.parametrize("family", ["unknown", "", None])
def test_adapter_not_dispatched(family):
    assert get_adapter(family) is None


# --------------------------------------------------------------------------- #
# Engine + cap settings
# --------------------------------------------------------------------------- #

def test_apply_engine_default_direct(monkeypatch):
    monkeypatch.delenv("APPLYPILOT_APPLY_ENGINE", raising=False)
    assert apply_settings.apply_engine() == "direct"


def test_apply_engine_direct_env(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_ENGINE", "DIRECT")
    assert apply_settings.apply_engine() == "direct"


def test_apply_engine_cli_override(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_APPLY_ENGINE", "claude")
    assert apply_settings.apply_engine("direct") == "direct"


def test_caps_defaults(monkeypatch):
    monkeypatch.delenv("APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY", raising=False)
    monkeypatch.delenv("APPLYPILOT_MAX_PER_APEX_DOMAIN_PER_DAY", raising=False)
    assert apply_settings.max_per_ats_family_per_day() == 75
    assert apply_settings.max_per_apex_domain_per_day() == 25


def test_caps_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY", "notanint")
    assert apply_settings.max_per_ats_family_per_day() == 75


# --------------------------------------------------------------------------- #
# Throttle (isolated DB)
# --------------------------------------------------------------------------- #

def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    import applypilot.config as cfg
    importlib.reload(cfg)
    import applypilot.database as db
    importlib.reload(db)
    return db


def test_throttle_allows_under_cap(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    conn = db.get_connection()
    allowed, reason = throttle.check_caps(
        "https://job-boards.greenhouse.io/acme/jobs/1", conn=conn
    )
    assert allowed and reason is None


def test_throttle_blocks_family_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY", "2")
    monkeypatch.setenv("APPLYPILOT_MAX_PER_APEX_DOMAIN_PER_DAY", "0")  # disable domain cap
    db = _fresh_db(tmp_path, monkeypatch)
    conn = db.get_connection()
    for i in range(2):
        db.record_apply_outcome(
            conn=conn,
            url=f"https://job-boards.greenhouse.io/acme{i}/jobs/{i}",
            ats_family="greenhouse",
            result="applied",
        )
    allowed, reason = throttle.check_caps(
        "https://job-boards.greenhouse.io/acme/jobs/99", conn=conn
    )
    assert not allowed
    assert reason == "deferred:direct_family_cap:greenhouse"
    assert throttle.is_cap_defer(reason)


def test_count_submits_today_matches_outcomes(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    conn = db.get_connection()
    db.record_apply_outcome(
        conn=conn,
        url="https://job-boards.greenhouse.io/acme/jobs/1",
        ats_family="greenhouse",
        result="applied",
    )
    db.record_apply_outcome(
        conn=conn,
        url="https://job-boards.greenhouse.io/acme/jobs/2",
        ats_family="greenhouse",
        result="failed:direct_unresolved_required",
    )
    assert throttle.count_submits_today(conn=conn) == 1


def test_throttle_ignores_non_submit_results(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLYPILOT_MAX_PER_ATS_FAMILY_PER_DAY", "1")
    monkeypatch.setenv("APPLYPILOT_MAX_PER_APEX_DOMAIN_PER_DAY", "0")
    db = _fresh_db(tmp_path, monkeypatch)
    conn = db.get_connection()
    # An escalation/failure didn't spend IP trust -> shouldn't consume a slot.
    db.record_apply_outcome(
        conn=conn,
        url="https://job-boards.greenhouse.io/acme/jobs/1",
        ats_family="greenhouse",
        result="failed:direct_unresolved_required",
    )
    allowed, _ = throttle.check_caps(
        "https://job-boards.greenhouse.io/acme/jobs/2", conn=conn
    )
    assert allowed


# --------------------------------------------------------------------------- #
# Driver early-exit gates (no browser needed)
# --------------------------------------------------------------------------- #

def test_driver_escalates_unknown_family():
    job = {"application_url": "https://careers.example.com/job/1"}
    dr = driver.apply_via_direct(job, port=0, worker_id=0, dry_run=True)
    assert dr.result == "failed:direct_no_adapter"
    assert dr.escalate is True
    assert dr.ats_family == "unknown"


def test_driver_no_url():
    job = {"site": "Greenhouse:Acme"}
    dr = driver.apply_via_direct(job, port=0, worker_id=0, dry_run=True)
    assert dr.result == "failed:direct_no_adapter"  # unknown family from empty url


def test_checkbox_group_uses_gemini_when_deterministic_rules_do_not_apply(monkeypatch):
    from applypilot.apply.direct.profile_binding import Field

    members = [
        Field(
            label="Interview engineering",
            type="checkbox",
            tag="input",
            name_attr="background",
            section_header="Which background best describes you?",
            required=True,
            key="bg_1",
        ),
        Field(
            label="Software engineering",
            type="checkbox",
            tag="input",
            name_attr="background",
            section_header="Which background best describes you?",
            required=True,
            key="bg_2",
        ),
    ]

    class Outcome:
        answers = {"checkbox_group|background": "Software engineering"}
        via = {"checkbox_group|background": "t2:gemini"}

    monkeypatch.setattr(driver.resolver, "resolve", lambda *a, **k: Outcome())

    pick, via = driver._resolve_checkbox_group_pick(
        members,
        tokens={"full_name": "Rachit Srivastava"},
        job={"title": "Full-Stack Engineer"},
        gemini_enabled=True,
    )

    assert pick == "Software engineering"
    assert via == "t2:gemini"


def test_checkbox_group_stays_unresolved_when_gemini_disabled():
    from applypilot.apply.direct.profile_binding import Field

    members = [
        Field(
            label="AWS",
            type="checkbox",
            tag="input",
            name_attr="certs",
            section_header="Which certifications do you hold?",
            required=True,
            key="cert_1",
        ),
        Field(
            label="GCP",
            type="checkbox",
            tag="input",
            name_attr="certs",
            section_header="Which certifications do you hold?",
            required=True,
            key="cert_2",
        ),
    ]

    pick, via = driver._resolve_checkbox_group_pick(
        members,
        tokens={},
        gemini_enabled=False,
    )

    assert pick is None
    assert via == ""


@pytest.mark.parametrize("url,expected", [
    # custom-domain Greenhouse -> hosted embed form
    ("https://careers.datadoghq.com/detail/7683726/?gh_jid=7683726",
     "https://boards.greenhouse.io/embed/job_app?token=7683726"),
    ("https://databricks.com/company/careers/open-positions/job?gh_jid=8099751002",
     "https://boards.greenhouse.io/embed/job_app?token=8099751002"),
    # already native -> unchanged
    ("https://job-boards.greenhouse.io/anthropic/jobs/5146028008",
     "https://job-boards.greenhouse.io/anthropic/jobs/5146028008"),
    # no token -> unchanged
    ("https://careers.example.com/jobs/123",
     "https://careers.example.com/jobs/123"),
])
def test_canonical_apply_url_greenhouse(url, expected):
    assert driver._canonical_apply_url(url, "greenhouse") == expected


def test_canonical_apply_url_non_greenhouse_untouched():
    u = "https://jobs.ashbyhq.com/X/abc?gh_jid=9"
    assert driver._canonical_apply_url(u, "ashby") == u


@pytest.mark.parametrize("url,expected", [
    (
        "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/Mumbai-India/Frontend-Engineer_R263770",
        "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/Mumbai-India/Frontend-Engineer_R263770/apply",
    ),
    (
        "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/Mumbai-India/Frontend-Engineer_R263770/apply",
        "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/Mumbai-India/Frontend-Engineer_R263770/apply",
    ),
    (
        "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/Mumbai-India/Frontend-Engineer_R263770/apply/applyManually",
        "https://blackrock.wd1.myworkdayjobs.com/BlackRock_Professional/job/Mumbai-India/Frontend-Engineer_R263770/apply/applyManually",
    ),
])
def test_canonical_apply_url_workday(url, expected):
    assert driver._canonical_apply_url(url, "workday") == expected


class _FakePage:
    """Minimal stand-in for a Playwright page for content-sniff tests."""

    def __init__(self, *, html="", resource_urls=(), url="https://acme.jobs/x"):
        self._html = html
        self._resource_urls = list(resource_urls)
        self.url = url

    def eval_on_selector_all(self, _selector, _js):
        return list(self._resource_urls)

    def content(self):
        return self._html


def test_content_sniff_detects_greenhouse_iframe(no_skip_ats):
    page = _FakePage(
        resource_urls=["https://boards.greenhouse.io/embed/job_app?token=7862086"],
    )
    family, form_url = driver._content_sniff_family(page)
    assert family == "greenhouse"
    assert form_url == "https://boards.greenhouse.io/embed/job_app?token=7862086"


def test_content_sniff_detects_greenhouse_from_markers_no_form_url(no_skip_ats):
    page = _FakePage(html='<div id="grnhse_app"></div>')
    family, form_url = driver._content_sniff_family(page)
    assert family == "greenhouse"
    assert form_url is None  # inline embed: fill in place, no re-navigation


def test_content_sniff_unknown_page_stays_unknown():
    page = _FakePage(html="<html><body>Careers</body></html>")
    family, form_url = driver._content_sniff_family(page)
    assert family == "unknown"
    assert form_url is None


def test_driver_matches_any():
    assert driver._matches_any("thank you for applying", ("thank you for",))
    assert not driver._matches_any("loading...", ("thank you for",))
    from applypilot.apply.direct.generic import ADAPTER

    assert driver._matches_any(
        "you have already applied for this job",
        ADAPTER.success_markers,
    )


def test_record_row_shape():
    row = driver._record_row("Phone", "+918168433423", ftype="tel", via="t0:attr")
    assert row["label"] == "Phone"
    assert row["value"] == "+918168433423"
    assert row["empty"] is False
    assert row["source"] == "direct:t0:attr"


def test_required_empty_fields_ignores_satisfied_checkbox_group():
    from applypilot.apply.direct.profile_binding import Field

    form = driver.extractor.FormState(
        fields=[
            Field(label="AWS", type="checkbox", tag="input", name_attr="certs",
                  section_header="Certs", required=True, key="c1"),
            Field(label="GCP", type="checkbox", tag="input", name_attr="certs",
                  section_header="Certs", required=True, key="c2", value="checked"),
        ]
    )
    assert driver._required_empty_fields(form) == []


def test_required_empty_fields_ignores_workday_progress_stepper():
    from applypilot.apply.direct.profile_binding import Field

    form = driver.extractor.FormState(
        fields=[
            Field(
                label="completed step 1 of 4",
                type="",
                tag="ul",
                name_attr="",
                section_header="",
                required=True,
                key="stepper",
            ),
            Field(
                label="Email",
                type="email",
                tag="input",
                name_attr="email",
                section_header="Contact",
                required=True,
                key="email",
            ),
        ]
    )
    assert driver._required_empty_fields(form) == [form.fields[1]]


def test_partition_checkbox_radio_groups():
    from applypilot.apply.direct.profile_binding import Field

    non_combo = [
        Field(label="Python", type="checkbox", section_header="Tech stack", key="t1"),
        Field(label="Java", type="checkbox", section_header="Tech stack", key="t2"),
        Field(label="Yes", type="radio", name_attr="auth", key="r1"),
        Field(label="No", type="radio", name_attr="auth", key="r2"),
    ]
    cbg, rg, multi_cb, multi_radio, member_keys = driver._partition_checkbox_radio_groups(
        non_combo
    )
    assert len(cbg["section:Tech stack"]) == 2
    assert multi_cb == ["section:Tech stack"]
    assert "auth" not in multi_radio
    assert member_keys == {"t1", "t2"}


def test_file_hint_classifiers():
    assert driver._file_hint_is_cover("Cover letter (optional)")
    assert not driver._file_hint_is_cover(
        "input_files_input_F3bomLqD20FjxxV9 input_files_input_F3bomLqD20FjxxV9"
    )
    assert driver._upload_accepts_images_only(".jpg,.jpeg,.gif,.png,image/jpeg")
    assert driver._is_cover_file_upload(
        {
            "label": "Cover letter",
            "name": "cover",
            "accept": ".pdf",
            "required": False,
        },
        family="workable",
    )
    assert not driver._is_cover_file_upload(
        {
            "label": "input_files_input_x",
            "name": "input_files_input_x",
            "accept": ".jpg,.jpeg,.png,image/png",
            "required": False,
        },
        family="workable",
    )
    assert driver._file_hint_is_resume("Upload resume / CV")
    assert driver._file_hint_is_resume("Replace file")
    assert driver._file_hint_is_photo("Profile photo")


def test_enrich_audit_file_rows_fills_empty_file_values():
    from applypilot.apply.direct import extractor

    class _Page:
        def inner_text(self, _sel: str) -> str:
            return "senior-full-stack-engineer.pdf uploaded"

    form = extractor.FormState(
        fields=[
            extractor.Field(
                label="Attach",
                type="file",
                tag="input",
                name_attr="cover_letter",
            ),
        ],
    )
    audit_rows = [
        driver._record_row("Attach", "", ftype="file", via="dom"),
    ]
    uploads = [
        {
            "label": "Attach",
            "name": "cover_letter",
            "required": False,
            "has_file": False,
            "file_name": "",
        },
    ]
    resume_path = "/tmp/role_resumes/senior-full-stack-engineer.pdf"
    driver._enrich_audit_file_rows(
        audit_rows,
        form,
        uploads,
        resume_pdf=resume_path,
        cover_pdf=None,
        page=_Page(),
        family="greenhouse",
    )
    assert audit_rows[0]["label"] == "Resume (PDF)"
    assert resume_path in audit_rows[0]["value"]
    assert audit_rows[1]["value"] == ""


def test_page_shows_filename():
    class _Page:
        def inner_text(self, _sel: str) -> str:
            return "Attached senior-full-stack-engineer.pdf"

    assert driver._page_shows_filename(_Page(), "senior-full-stack-engineer.pdf")
    assert not driver._page_shows_filename(_Page(), "ab")


def test_ashby_autofill_file_is_not_submission_resume():
    from applypilot.apply.direct.profile_binding import Field

    autofill = Field(label="Autofill from resume", type="file", tag="input")
    required = Field(
        label="Resume",
        type="file",
        tag="input",
        name_attr="_systemfield_resume",
    )

    assert driver._is_ashby_autofill_file(autofill) is True
    assert driver._is_ashby_autofill_file(required) is False


# --------------------------------------------------------------------------- #
# Field overrides — user corrections applied to all future forms
# --------------------------------------------------------------------------- #

def test_field_override_roundtrip_and_normalization(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.set_field_override("Phone", "+91 8168433423")
    # Different casing / punctuation in the label still resolves the same key.
    assert db.get_field_override("phone") == "+91 8168433423"
    assert db.get_field_override("PHONE  ") == "+91 8168433423"
    assert db.get_field_override("Email") is None


def test_field_override_wins_in_resolver(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    from applypilot.apply.direct import resolver
    from applypilot.apply.direct.profile_binding import Field

    # Rule would map First name -> "Rachit"; override must win.
    db.set_field_override("First name", "Ravi")
    fields = [Field(label="First name", type="text", tag="input", key="k1")]
    out = resolver.resolve(fields, {"full_name": "Rachit Srivastava"},
                           conn=db.get_connection(), gemini_enabled=False)
    assert out.answers["k1"] == "Ravi"
    assert out.via["k1"] == "override:user"


def test_field_override_delete(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    db.set_field_override("Phone", "x")
    assert db.delete_field_override("Phone") is True
    assert db.get_field_override("Phone") is None


def test_resolve_radio_group_relocation_without_gemini():
    from applypilot.apply.direct.profile_binding import Field

    members = [
        Field(
            label="Yes, open to relocation",
            type="radio",
            tag="input",
            name_attr="relocation",
            key="r1",
        ),
        Field(
            label="No, not open to relocation",
            type="radio",
            tag="input",
            name_attr="relocation",
            key="r2",
        ),
    ]
    pick, via = driver._resolve_radio_group_pick(
        members, tokens={}, gemini_enabled=False
    )
    assert pick == "Yes, open to relocation"
    assert via == "label"


def test_resolve_radio_group_lever_yes_no_with_section_without_gemini():
    from applypilot.apply.direct.profile_binding import Field

    question = (
        "Would you require sponsorship for employment visa status "
        "either now or in the future?"
    )
    members = [
        Field(
            label="Yes",
            type="radio",
            tag="input",
            name_attr="cards[x][field1]",
            section_header=question,
            key="y",
        ),
        Field(
            label="No",
            type="radio",
            tag="input",
            name_attr="cards[x][field1]",
            section_header=question,
            key="n",
        ),
    ]
    pick, via = driver._resolve_radio_group_pick(
        members,
        tokens={"require_sponsorship": "No"},
        gemini_enabled=False,
    )
    assert pick == "No"
    assert via == "label"


def test_lever_extractor_populates_section_header_for_card_radios():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import extractor

    html = """
    <html><body>
      <div class="application-label full-width multiple-choice">
        <div class="text">Are you currently legally eligible for employment in the United States? <span class="required">✱</span></div>
      </div>
      <div class="application-field full-width required-field">
        <ul><li><label><input type="radio" name="cards[abc][field0]" value="Yes" required><span>Yes</span></label></li>
        <li><label><input type="radio" name="cards[abc][field0]" value="No" required><span>No</span></label></li></ul>
      </div>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        browser.close()
    radios = [f for f in state.fields if f.type == "radio"]
    assert len(radios) == 2
    assert all("legally eligible" in (f.section_header or "").lower() for f in radios)


def test_lever_extractor_card_text_uses_application_label_not_ancestor():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import extractor

    html = """
    <html><body>
      <div class="application-label"><div class="text">Resume/CV ✱</div></div>
      <div class="application-field"><input type="file" name="resume"></div>
      <div class="application-label full-width"><div class="text">Share your salary expectations ✱</div></div>
      <div class="application-field full-width required-field">
        <input required class="card-field-input" type="text" name="cards[x][field0]" placeholder="Type your response">
      </div>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        browser.close()
    text_fields = [f for f in state.fields if f.tag == "input" and f.type == "text"]
    assert len(text_fields) == 1
    assert "salary" in text_fields[0].label.lower()


def test_lever_extractor_select_uses_application_label_not_distant_aria():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import extractor

    html = """
    <html><body>
      <div class="application-label full-width multiple-choice">
        <div class="text">Kindly select all the technologies you are hands on with? ✱</div>
      </div>
      <div class="application-field full-width required-field">
        <label><input type="checkbox" name="cards[t][field0]" value="React"><span>React</span></label>
      </div>
      <div class="application-label full-width">
        <div class="text">This is a Remote role via Deel ✱</div>
      </div>
      <div class="application-field full-width required-field">
        <select required name="cards[t][field7]" aria-labelledby="wrong-tech-label">
          <option>Select...</option><option>Yes</option><option>No</option>
        </select>
      </div>
      <div id="wrong-tech-label" hidden>Kindly select all the technologies you are hands on with?</div>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        browser.close()
    selects = [f for f in state.fields if f.tag == "select"]
    assert len(selects) == 1
    assert "remote role" in selects[0].label.lower()
    assert "deel" in selects[0].label.lower()
    assert "technolog" not in selects[0].label.lower()


def test_click_radio_group_option_scoped_by_name_attr():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import extractor, driver

    html = """
    <html><body>
      <div class="application-label"><div class="text">Eligible for US employment?</div></div>
      <div class="application-field">
        <label><input type="radio" name="cards[a][field0]" value="Yes"><span>Yes</span></label>
        <label><input type="radio" name="cards[a][field0]" value="No"><span>No</span></label>
      </div>
      <div class="application-label"><div class="text">Need sponsorship?</div></div>
      <div class="application-field">
        <label><input type="radio" name="cards[a][field1]" value="Yes"><span>Yes</span></label>
        <label><input type="radio" name="cards[a][field1]" value="No"><span>No</span></label>
      </div>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        groups = driver._radio_groups_from_form(state)
        members = groups["cards[a][field1]"]
        assert driver._click_radio_group_option(page, members, "No")
        assert driver._radio_group_is_checked(page, "cards[a][field1]")
        assert not driver._radio_group_is_checked(page, "cards[a][field0]")
        browser.close()


def test_fill_text_field_stable_by_name_and_label():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import driver, extractor

    html = """
    <html><body>
      <label for="fname">* First name</label>
      <input id="fname" name="first_name" type="text" required>
      <label for="notice">* Notice Period</label>
      <input id="notice" name="notice_period" type="text" required>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        first = next(f for f in state.fields if "first name" in f.label.lower())
        notice = next(f for f in state.fields if "notice" in f.label.lower())
        assert driver._fill_text_field_stable(page, first, "Rachit")
        assert driver._fill_text_field_stable(page, notice, "Immediately")
        assert page.input_value("#fname") == "Rachit"
        assert page.input_value("#notice") == "Immediately"
        browser.close()


def test_extractor_skips_workable_ca_companion_proxy():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import extractor

    html = """
    <html><body>
      <label for="firstname">* First name</label>
      <input id="firstname" name="firstname" type="text" required>
      <input name="CA_32652" type="text" required aria-label="* First name">
      <input name="input_CA_32652_input" type="text">
      <label for="notice">* Notice Period</label>
      <input id="notice" name="CA_25140" type="text" required>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        names = {f.name_attr for f in state.fields}
        browser.close()
    assert "firstname" in names
    assert "CA_25140" in names
    assert "CA_32652" not in names
    assert "input_CA_32652_input" not in names


def test_extractor_ignores_hidden_error_templates():
    """Lever keeps upload error copy in hidden .error-message nodes — not visible errors."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from applypilot.apply.direct import extractor

    html = """
    <html><body>
      <div class="error-message" style="display:none">
        File exceeds the maximum upload size of 100MB. Please try a smaller size.
      </div>
      <div class="resume-upload-failure" hidden>Couldn't auto-read resume.</div>
      <label for="email">Email</label>
      <input id="email" name="email" type="email" required>
      <div class="field-error" role="alert">Email is required</div>
    </body></html>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        state = extractor.extract_fields(page)
        browser.close()
    assert state.visible_errors == ["Email is required"]


def test_is_transient_submit_error():
    from applypilot.apply.direct.driver import _is_transient_submit_error

    assert _is_transient_submit_error(
        ["Something went wrong. We are working on this, please try again later."]
    )
    assert not _is_transient_submit_error(["Phone number is required"])


def test_looks_like_non_application_form():
    from applypilot.apply.direct import extractor, unblock

    fields = [
        extractor.Field(label="Email", type="text", tag="input"),
        extractor.Field(label="Password", type="password", tag="input"),
        extractor.Field(label="Share your feedback", type="textarea", tag="textarea"),
    ]
    assert unblock.looks_like_non_application_form(fields)
    assert not unblock.looks_like_non_application_form([
        extractor.Field(label="First name", type="text", tag="input"),
        extractor.Field(label="Last name", type="text", tag="input"),
        extractor.Field(label="Email", type="email", tag="input"),
        extractor.Field(label="Resume", type="file", tag="input"),
    ])


def test_review_only_multistep_page_skips_empty_confirmation():
    from applypilot.apply.direct import extractor

    assert driver._is_review_only_multistep_page([]) is True
    assert driver._is_review_only_multistep_page([
        extractor.Field(label="Submit application", type="submit", tag="button"),
    ]) is True


def test_review_only_multistep_page_keeps_optional_screening():
    from applypilot.apply.direct import extractor

    micro1 = [
        extractor.Field(
            label="How many years of experience do you have working with React?",
            type="number",
            tag="input",
        ),
        extractor.Field(
            label="What is your expected hourly rate in USD?",
            type="number",
            tag="input",
        ),
    ]
    assert driver._is_review_only_multistep_page(micro1) is False
