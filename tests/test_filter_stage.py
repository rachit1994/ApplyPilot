from __future__ import annotations

import pytest

from applypilot.scoring import filter_stage


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    from applypilot import database

    db_path = tmp_path / "filter.db"
    database.init_db()
    yield
    database.close_connection()


def test_run_filter_rejects_and_keeps_jobs(temp_db, monkeypatch):
    from applypilot.database import get_connection

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, location, description, full_description, detail_scraped_at, discovered_at)
        VALUES
          ('https://jobs.example/junior', 'Junior Engineer', 'Example', 'Remote', 'Build APIs.', 'Build APIs.', '2026-06-04T00:00:00+00:00', '2026-06-04T00:00:00+00:00'),
          ('https://jobs.example/senior', 'Senior Frontend Engineer', 'Example', 'Remote', 'React TypeScript UI platform work.', 'React TypeScript UI platform work.', '2026-06-04T00:01:00+00:00', '2026-06-04T00:01:00+00:00')
        """
    )
    conn.commit()

    monkeypatch.setattr(
        filter_stage,
        "load_profile",
        lambda: {
            "experience": {"target_roles": ["Senior Frontend Engineer"]},
            "skills_boundary": {"frameworks": ["React"], "languages": ["TypeScript"]},
            "compensation": {"salary_currency": "INR"},
        },
    )
    monkeypatch.setattr(filter_stage, "load_search_config", lambda: {})

    summary = filter_stage.run_filter(conn=conn)

    assert summary["checked"] == 2
    assert summary["rejected"] == 1
    assert summary["kept"] == 1

    rows = {
        row["url"]: row
        for row in conn.execute(
            """
            SELECT url, pre_fit_score, pre_filter_reason, pre_filter_rejected_at,
                   fit_score, detail_scraped_at
            FROM jobs
            """
        ).fetchall()
    }
    rejected = rows["https://jobs.example/junior"]
    assert rejected["pre_filter_reason"] == "title:junior_or_intern"
    assert rejected["fit_score"] == 1
    assert rejected["detail_scraped_at"] is not None

    kept = rows["https://jobs.example/senior"]
    assert kept["pre_fit_score"] is not None
    assert kept["pre_filter_reason"] is None
    assert kept["fit_score"] is None
    assert kept["detail_scraped_at"] is not None
