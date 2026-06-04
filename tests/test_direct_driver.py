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

def test_greenhouse_adapter_dispatched():
    adapter = get_adapter("greenhouse")
    assert adapter is not None
    assert adapter.family == "greenhouse"
    assert adapter.submit_button_texts


@pytest.mark.parametrize("family", ["lever", "ashby"])
def test_lever_ashby_adapter_dispatched(family):
    adapter = get_adapter(family)
    assert adapter is not None
    assert adapter.family == family


@pytest.mark.parametrize("family", ["workday", "unknown", "", None])
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


def test_content_sniff_detects_greenhouse_iframe():
    page = _FakePage(
        resource_urls=["https://boards.greenhouse.io/embed/job_app?token=7862086"],
    )
    family, form_url = driver._content_sniff_family(page)
    assert family == "greenhouse"
    assert form_url == "https://boards.greenhouse.io/embed/job_app?token=7862086"


def test_content_sniff_detects_greenhouse_from_markers_no_form_url():
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


def test_record_row_shape():
    row = driver._record_row("Phone", "+918168433423", ftype="tel", via="t0:attr")
    assert row["label"] == "Phone"
    assert row["value"] == "+918168433423"
    assert row["empty"] is False
    assert row["source"] == "direct:t0:attr"


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
