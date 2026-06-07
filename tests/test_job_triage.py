"""Jobs tab triage filters: chip counts must match list totals."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from applypilot.server.job_triage import TRIAGE_SLUGS, fetch_triage_counts, normalize_triage_slug


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        monkeypatch.setenv("APPLYPILOT_DIR", tmp)
        from applypilot import config
        from applypilot import database
        from applypilot.orchestration import events

        config.load_env()
        monkeypatch.setattr(config, "APP_DIR", Path(tmp))
        database.close_connection()
        yield db
        database.close_connection()


def _seed_jobs(conn) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, discovered_at,
            tailored_resume_path, cover_letter_path, apply_status, apply_error
        )
        VALUES
          ('https://ex/new', 'New scored', 'Acme', 7,
           '2026-05-18T10:00:00+00:00', NULL, NULL, NULL, NULL),
          ('https://ex/ready', 'Saved ready', 'Acme', 8,
           '2026-05-18T11:00:00+00:00', '/tmp/r.pdf', NULL, NULL, NULL),
          ('https://ex/tailored', 'Tailored only', 'Acme', 8,
           '2026-05-18T12:00:00+00:00', '/tmp/r2.pdf', '/tmp/c.pdf', NULL, NULL),
          ('https://ex/applied', 'Submitted', 'Acme', 9,
           '2026-05-18T13:00:00+00:00', '/tmp/r3.pdf', NULL, 'applied', NULL),
          ('https://ex/failed', 'Failed apply', 'Acme', 8,
           '2026-05-18T14:00:00+00:00', '/tmp/r4.pdf', NULL, 'failed', 'timeout'),
          ('https://ex/pending', 'Not scored yet', 'Beta', NULL,
           '2026-05-18T15:00:00+00:00', NULL, NULL, NULL, NULL)
        """
    )
    conn.commit()


def test_triage_counts_match_query_jobs_total(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app
    from applypilot.server.jobs import query_jobs
    from applypilot.server.stats import fetch_stats

    init_db()
    conn = get_connection()
    _seed_jobs(conn)

    counts = fetch_triage_counts(conn)
    stats = fetch_stats()
    assert stats.triage_counts == counts

    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        create_app()
    )
    api_stats = client.get("/api/stats").json()["stats"]
    assert api_stats["triage_counts"] == counts

    for slug in sorted(TRIAGE_SLUGS):
        _, total = query_jobs(stage=slug, limit=500)
        assert total == counts[slug], f"{slug}: list total {total} != count {counts[slug]}"


def test_triage_aliases_and_legacy_stage_param(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app

    init_db()
    _seed_jobs(get_connection())

    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        create_app()
    )
    assert normalize_triage_slug("scored") == "new"
    new_via_alias = client.get("/api/jobs", params={"stage": "scored"}).json()
    new_explicit = client.get("/api/jobs", params={"stage": "new"}).json()
    assert new_via_alias["total"] == new_explicit["total"]
    assert new_via_alias["total"] >= 1

    assert client.get("/api/jobs", params={"stage": "submitted"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"stage": "not_a_real_stage"}).json()["total"] == 0


def test_triage_counts_endpoint_respects_min_score(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app
    from applypilot.server.jobs import query_jobs

    init_db()
    _seed_jobs(get_connection())

    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        create_app()
    )
    global_counts = client.get("/api/jobs/triage-counts").json()["counts"]
    filtered = client.get("/api/jobs/triage-counts", params={"min_score": 8}).json()[
        "counts"
    ]

    assert global_counts["all"] >= filtered["all"]
    for slug in sorted(TRIAGE_SLUGS):
        _, list_total = query_jobs(stage=slug, min_score=8, limit=500)
        assert filtered[slug] == list_total, (
            f"min_score=8 {slug}: triage-counts {filtered[slug]} != list {list_total}"
        )
