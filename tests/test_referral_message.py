"""Tests for referral note finalization."""

from applypilot.outreach.referral_draft import finalize_referral_message


def test_finalize_adds_custom_resume_attach_sentence():
    raw = "I applied for the Staff Engineer role at Walmart. Led a team that cut deploy time 40%."
    out = finalize_referral_message(
        raw,
        job_title="Staff Software Engineer",
        company="Walmart",
    )
    assert "custom-made resume" in out.lower()
    assert "attached" in out.lower()


def test_finalize_strips_banned_opener():
    raw = (
        "I hope this finds you well. I applied for the Backend Engineer role at Acme. "
        "Shipped payments at scale."
    )
    out = finalize_referral_message(raw, job_title="Backend Engineer", company="Acme")
    assert "hope this finds you well" not in out.lower()
    assert "custom-made resume" in out.lower()


def test_finalize_prepends_role_if_missing():
    raw = "Built APIs serving 2M requests/day. Would you refer me?"
    out = finalize_referral_message(
        raw,
        job_title="Senior Engineer",
        company="NiCE",
    )
    assert out.lower().startswith("i applied for the senior engineer role at nice")
    assert "attached" in out.lower()
