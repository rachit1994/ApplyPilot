"""ATS URL extraction from inbox message text."""

from applypilot.inbox.ats import apply_ats_boost, extract_ats_from_text, mentions_apply_signal


def test_extract_greenhouse_url():
    text = "Apply here: https://boards.greenhouse.io/acme/jobs/12345?gh_jid=1"
    out = extract_ats_from_text(text)
    assert out["ats_vendor"] == "greenhouse"
    assert "greenhouse.io" in out["apply_url"]


def test_extract_lever_url():
    text = "Link: https://jobs.lever.co/company/abc-123"
    out = extract_ats_from_text(text)
    assert out["ats_vendor"] == "lever"
    assert "lever.co" in out["apply_url"]


def test_ats_boost_never_overrides_rejection():
    intent, conf, boosted = apply_ats_boost(
        intent="rejection",
        confidence=0.5,
        apply_url="https://boards.greenhouse.io/x/y",
        latest_inbound="please apply via this link",
    )
    assert intent == "rejection"
    assert boosted is False


def test_ats_boost_apply_request():
    intent, conf, boosted = apply_ats_boost(
        intent="other",
        confidence=0.6,
        apply_url="https://jobs.lever.co/co/role",
        latest_inbound="Please apply using the link",
    )
    assert intent == "apply_request"
    assert conf >= 0.92
    assert boosted is True


def test_mentions_apply_signal():
    assert mentions_apply_signal("Send your CV to proceed")
    assert not mentions_apply_signal("Thanks for connecting")
