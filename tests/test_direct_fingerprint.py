"""Tests for ATS family / provider fingerprint detection."""

from applypilot.apply.direct import fingerprint as fp
from applypilot.apply.direct.adapters import get_adapter


def test_family_from_known_hosts():
    assert fp.ats_family("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert fp.ats_family("https://grnh.se/abc123") == "greenhouse"
    assert fp.ats_family("https://jobs.lever.co/acme/uuid") == "lever"
    assert fp.ats_family("https://jobs.ashbyhq.com/acme/uuid") == "ashby"
    assert fp.ats_family("https://acme.wd5.myworkdayjobs.com/en-US/careers") == "workday"
    assert (
        fp.ats_family("https://www.workatastartup.com/application?signup_job_id=123")
        == "workatastartup"
    )
    assert fp.ats_family("https://careers.icims.com/jobs/1") == "icims"


def test_family_unknown_for_non_ats():
    assert fp.ats_family("https://www.linkedin.com/jobs/view/123") == "unknown"
    assert fp.ats_family("https://example.com/careers") == "unknown"
    assert fp.ats_family(None) == "unknown"
    assert fp.ats_family("") == "unknown"


def test_family_ignores_path_only_mentions():
    # A landing page that merely links to greenhouse must not be misclassified;
    # classification is host-based, not substring-in-path.
    assert fp.ats_family("https://example.com/apply?to=boards.greenhouse.io") == "unknown"


def test_family_from_query_param_on_custom_domain():
    # Greenhouse/Lever embedded on an employer's own careers domain — the
    # widget stamps a telltale query param even when the host isn't an ATS.
    assert fp.ats_family("https://stripe.com/jobs/search?gh_jid=7532733") == "greenhouse"
    assert fp.ats_family("https://careers.airbnb.com/positions/7649441?gh_jid=764") == "greenhouse"
    assert fp.ats_family("https://jobs.example.com/x?lever-source=foo") == "lever"


def test_sniff_family_from_embedded_greenhouse_iframe():
    # Custom career domain whose URL is 'unknown' but whose page embeds the
    # hosted Greenhouse form -> detect greenhouse from the iframe src.
    urls = ["https://boards.greenhouse.io/embed/job_app?token=7862086"]
    assert fp.sniff_ats_family(html="<html></html>", embedded_urls=urls) == "greenhouse"


def test_sniff_family_from_greenhouse_named_script():
    # dropbox.jobs loads a custom-hosted but greenhouse-named apply script; the
    # filename alone is a definitive tell even though the host isn't greenhouse.
    urls = ["https://www.dropbox.jobs/scripts/forms/greenhouseApplyForm.js?v=abc"]
    assert fp.sniff_ats_family(html="", embedded_urls=urls) == "greenhouse"


def test_sniff_family_from_content_markers():
    html = '<div id="grnhse_app"></div><footer>Powered by Greenhouse</footer>'
    assert fp.sniff_ats_family(html=html, embedded_urls=[]) == "greenhouse"
    assert fp.sniff_ats_family(html="application--form", embedded_urls=[]) == "greenhouse"


def test_sniff_family_unknown_without_markers():
    html = "<html><body>Apply on our careers site</body></html>"
    assert fp.sniff_ats_family(html=html, embedded_urls=[]) == "unknown"
    assert fp.sniff_ats_family(html=None, embedded_urls=[]) == "unknown"


def test_sniff_family_embedded_url_wins_over_unknown_host():
    # A page on a non-ATS host that embeds a Lever widget reads as lever.
    urls = ["https://jobs.lever.co/acme/uuid", "https://cdn.example.com/app.js"]
    assert fp.sniff_ats_family(html="", embedded_urls=urls) == "lever"


def test_greenhouse_form_url_prefers_job_app_iframe():
    urls = [
        "https://boards.greenhouse.io/embed/job_board/js?for=dropbox",
        "https://boards.greenhouse.io/embed/job_app?token=7862086",
    ]
    assert (
        fp.greenhouse_form_url(urls)
        == "https://boards.greenhouse.io/embed/job_app?token=7862086"
    )


def test_greenhouse_form_url_from_token_fallback():
    # No hosted job_app iframe, but a gh_jid token on a custom-domain embed.
    urls = ["https://stripe.com/jobs/search?gh_jid=7436194"]
    assert (
        fp.greenhouse_form_url(urls)
        == "https://boards.greenhouse.io/embed/job_app?token=7436194"
    )


def test_greenhouse_form_url_none_when_no_token():
    assert fp.greenhouse_form_url(["https://example.com/app.js"]) is None


def test_has_adapter_respects_skip_list(monkeypatch):
    monkeypatch.setenv("APPLYPILOT_SKIP_ATS_FAMILIES", "greenhouse,ashby")
    assert not fp.has_adapter("greenhouse")
    assert fp.has_adapter("lever")
    assert not fp.has_adapter("ashby")
    assert not fp.has_adapter("workday")
    assert fp.has_adapter("workatastartup")
    assert not fp.has_adapter("icims")
    assert not fp.has_adapter("unknown")
    assert not fp.has_adapter(None)


def test_has_adapter_when_skip_cleared(no_skip_ats):
    assert fp.has_adapter("greenhouse")
    assert fp.has_adapter("lever")
    assert fp.has_adapter("ashby")
    assert fp.has_adapter("workatastartup")
    assert get_adapter("workatastartup") is not None


def test_apex_domain():
    assert fp.apex_domain("https://acme.wd5.myworkdayjobs.com/x") == "myworkdayjobs.com"
    assert fp.apex_domain("https://boards.greenhouse.io/acme") == "greenhouse.io"
    assert fp.apex_domain("https://lever.co/x") == "lever.co"
    assert fp.apex_domain(None) == ""


def test_provider_fingerprint_stable():
    assert fp.provider_fingerprint("https://jobs.lever.co/x") == "lever:url"
    f1 = fp.provider_fingerprint("https://jobs.lever.co/x", "sig-a")
    f2 = fp.provider_fingerprint("https://jobs.lever.co/y", "sig-a")
    # Same DOM signature -> same fingerprint regardless of exact URL.
    assert f1 == f2 == "lever:" + f1.split(":")[1]
    # Different DOM signature -> different fingerprint.
    assert fp.provider_fingerprint("https://jobs.lever.co/x", "sig-b") != f1
