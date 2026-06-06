from unittest.mock import patch

from applypilot.discovery.ats.ashby import fetch_board_jobs


@patch("applypilot.discovery.ats.ashby.get_json")
def test_fetch_board_jobs_parses_public_posting_api(mock_get_json):
    mock_get_json.return_value = {
        "jobs": [
            {
                "title": "Senior Frontend Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/job-id",
                "applyUrl": "https://jobs.ashbyhq.com/acme/job-id/application",
                "location": "Bengaluru",
                "isRemote": True,
                "workplaceType": "Remote",
                "descriptionHtml": "<p>Build product UI.</p>",
                "compensation": [{"summary": "INR 60L"}],
            }
        ]
    }

    jobs = fetch_board_jobs("acme")

    assert jobs == [
        {
            "url": "https://jobs.ashbyhq.com/acme/job-id",
            "application_url": "https://jobs.ashbyhq.com/acme/job-id/application",
            "title": "Senior Frontend Engineer",
            "salary": "INR 60L",
            "description": "Build product UI.",
            "full_description": "Build product UI.",
            "location": "Bengaluru, Remote",
        }
    ]


@patch("applypilot.discovery.ats.ashby.get_json")
def test_fetch_board_jobs_does_not_mark_hybrid_jobs_remote(mock_get_json):
    mock_get_json.return_value = {
        "jobs": [
            {
                "title": "Staff AI Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/hybrid",
                "location": "San Francisco",
                "isRemote": True,
                "workplaceType": "Hybrid",
                "descriptionPlain": "Build AI systems.",
            }
        ]
    }

    [job] = fetch_board_jobs("acme")

    assert job["location"] == "San Francisco"
