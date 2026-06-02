"""Tests for ATS family / provider fingerprint detection."""

from applypilot.apply.direct import fingerprint as fp


def test_family_from_known_hosts():
    assert fp.ats_family("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert fp.ats_family("https://grnh.se/abc123") == "greenhouse"
    assert fp.ats_family("https://jobs.lever.co/acme/uuid") == "lever"
    assert fp.ats_family("https://jobs.ashbyhq.com/acme/uuid") == "ashby"
    assert fp.ats_family("https://acme.wd5.myworkdayjobs.com/en-US/careers") == "workday"
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


def test_has_adapter():
    assert fp.has_adapter("greenhouse")
    assert fp.has_adapter("lever")
    assert fp.has_adapter("ashby")
    assert fp.has_adapter("workday")
    assert not fp.has_adapter("icims")
    assert not fp.has_adapter("unknown")
    assert not fp.has_adapter(None)


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
