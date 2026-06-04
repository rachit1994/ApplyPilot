"""Job row presentation for dashboard API."""

from applypilot.server.job_present import infer_remote_policy, present_job_row


def test_infer_remote_policy():
    assert infer_remote_policy("Portugal, Remote") == "Remote"
    assert infer_remote_policy("New York, NY · Hybrid") == "Hybrid"
    assert infer_remote_policy("Bengaluru") == "On-site"
    assert infer_remote_policy(None) is None


def test_present_job_row_blanks_and_remote():
    row = present_job_row(
        {
            "url": "https://example.com/j",
            "title": "Eng",
            "location": "Germany, Remote",
            "salary": "",
            "fit_score": None,
            "apply_status": "",
        }
    )
    assert row["salary"] is None
    assert row["apply_status"] is None
    assert row["remote"] == "Remote"
