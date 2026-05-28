from applypilot.enrichment.detail import _decode_linkedin_redirect


def test_decode_linkedin_redirect_returns_target_url():
    url = "https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F123"
    assert _decode_linkedin_redirect(url) == "https://boards.greenhouse.io/acme/jobs/123"


def test_decode_linkedin_redirect_ignores_non_linkedin_hosts():
    url = "https://example.com/redir/redirect?url=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F123"
    assert _decode_linkedin_redirect(url) is None

