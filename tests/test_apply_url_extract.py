"""Tests for ATS URL extraction from job text."""

from applypilot.apply.apply_url_extract import (
    coerce_application_url,
    extract_best_apply_url_from_text,
)


def test_coerce_application_url_rejects_placeholders():
    assert coerce_application_url("None") is None
    assert coerce_application_url("nan") is None
    assert coerce_application_url("https://boards.greenhouse.io/x/jobs/1") == (
        "https://boards.greenhouse.io/x/jobs/1"
    )


def test_extract_workday_from_description():
    text = (
        "Apply here: https://company.wd5.myworkdayjobs.com/en-US/careers/job/123 "
        "or visit our site."
    )
    assert "myworkdayjobs.com" in extract_best_apply_url_from_text(text)


def test_extract_greenhouse_prefers_first_ats_link():
    text = (
        "See https://example.com/about and apply at "
        "https://boards.greenhouse.io/acme/jobs/99?gh_jid=99"
    )
    url = extract_best_apply_url_from_text(text)
    assert url and "greenhouse.io" in url
