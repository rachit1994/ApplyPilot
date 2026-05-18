"""Tests for dashboard run events and API."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        monkeypatch.setenv("APPLYPILOT_DIR", tmp)
        from applypilot.config import load_env

        load_env()
        yield db


def test_emit_run_event_noop_without_env(temp_db):
    from applypilot.database import init_db
    from applypilot.orchestration.events import emit_run_event, list_run_events

    init_db(temp_db)
    assert emit_run_event("stage_start", stage="discover") is None
    assert list_run_events("fake-id") == []


def test_emit_run_event_with_run_id(temp_db, monkeypatch):
    from applypilot.config import DB_PATH
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.orchestration.events import emit_run_event, init_run_schema, list_run_events

    close_connection()
    init_db()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES ('run-1', 'pipeline', 'running', '2026-05-18T00:00:00+00:00')
        """
    )
    conn.commit()

    monkeypatch.setenv("APPLYPILOT_RUN_ID", "run-1")
    event = emit_run_event("stage_start", stage="discover", message="starting discover")
    assert event is not None
    assert event["event_type"] == "stage_start"
    rows = list_run_events("run-1", db_path=str(DB_PATH))
    assert len(rows) == 1
    assert rows[0]["stage"] == "discover"


def test_api_stats_and_stages(temp_db):
    from applypilot.server.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert "stats" in body
    stats = body["stats"]
    assert "total" in stats
    assert "by_site" in stats
    assert "score_distribution" in stats
    assert "score_buckets" in stats
    assert "pipeline" in stats
    assert isinstance(stats["by_site"], list)
    assert len(stats["by_site"]) <= 5
    assert "scored" in stats["pipeline"]

    r2 = client.get("/api/meta/stages")
    assert r2.status_code == 200
    assert "discover" in r2.json()["order"]


def test_api_jobs_search_and_sort(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, fit_score, discovered_at)
        VALUES
          ('https://a.example/j1', 'Engineer at Acme', 'Acme Corp', 9, '2026-05-18T10:00:00+00:00'),
          ('https://b.example/j2', 'Designer', 'Beta LLC', 5, '2026-05-18T11:00:00+00:00')
        """
    )
    conn.commit()

    client = TestClient(create_app())
    by_company = client.get("/api/jobs", params={"search": "Acme"})
    assert by_company.status_code == 200
    data = by_company.json()
    assert data["total"] == 1
    assert data["jobs"][0]["site"] == "Acme Corp"

    by_title = client.get("/api/jobs", params={"search": "Designer"})
    assert by_title.json()["total"] == 1

    sorted_resp = client.get("/api/jobs", params={"sort": "fit_score_asc"})
    scores = [j["fit_score"] for j in sorted_resp.json()["jobs"]]
    assert scores == sorted(scores)


def test_start_pipeline_dry_run(temp_db, monkeypatch):
    from applypilot.server.app import create_app

    def fake_start(run_type, **kwargs):
        return {
            "id": "test-run-id",
            "run_type": "pipeline",
            "status": "running",
            "stages": ["discover"],
            "stream": False,
            "dry_run": True,
            "current_stage": None,
            "exit_code": None,
            "error_message": None,
            "started_at": "2026-05-18T00:00:00+00:00",
            "finished_at": None,
        }

    monkeypatch.setattr("applypilot.server.runs.start_typed_run", fake_start, raising=False)
    client = TestClient(create_app())
    r = client.post(
        "/api/runs",
        json={"dry_run": True, "stages": ["discover"]},
    )
    assert r.status_code == 200
    assert r.json()["id"] == "test-run-id"


def test_collect_new_db_events_dedupes(temp_db):
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.orchestration.events import emit_run_event, init_run_schema
    from applypilot.server.events import collect_new_db_events

    close_connection()
    init_db()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES ('run-poll', 'pipeline', 'running', '2026-05-18T00:00:00+00:00')
        """
    )
    conn.commit()

    emit_run_event("stage_start", stage="discover", run_id="run-poll")
    emit_run_event("stats_tick", run_id="run-poll", payload={"total": 1})
    emit_run_event("stage_end", stage="discover", run_id="run-poll")

    sent: set[int] = set()
    batch1, last_id, finished = collect_new_db_events("run-poll", 0, sent)
    assert len(batch1) == 3
    assert {e["event_type"] for e in batch1} == {"stage_start", "stats_tick", "stage_end"}
    assert finished is False

    batch2, last_id, finished = collect_new_db_events("run-poll", last_id, sent)
    assert batch2 == []
    assert finished is False

    emit_run_event("run_finished", run_id="run-poll", message="completed")
    batch3, _, finished = collect_new_db_events("run-poll", last_id, sent)
    assert len(batch3) == 1
    assert batch3[0]["event_type"] == "run_finished"
    assert finished is True

    batch4, _, _ = collect_new_db_events("run-poll", last_id, sent)
    assert batch4 == []

    row = conn.execute(
        "SELECT current_stage FROM runs WHERE id = ?", ("run-poll",)
    ).fetchone()
    assert row["current_stage"] == "discover"


def test_api_list_runs_includes_event_summary(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.orchestration.events import emit_run_event, init_run_schema
    from applypilot.orchestration.run_controller import list_runs
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES ('run-list', 'pipeline', 'completed', '2026-05-18T01:00:00+00:00')
        """
    )
    conn.commit()
    emit_run_event("log", run_id="run-list", message="tailored 3 jobs")

    runs = list_runs(limit=5)
    assert runs[0]["id"] == "run-list"
    assert runs[0]["event_count"] >= 1
    assert runs[0]["last_event_message"] == "tailored 3 jobs"

    client = TestClient(create_app())
    r = client.get("/api/runs?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == "run-list"
    assert body[0]["event_count"] >= 1


def test_events_history_endpoint(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.orchestration.events import emit_run_event, init_run_schema
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES ('run-hist', 'pipeline', 'running', '2026-05-18T00:00:00+00:00')
        """
    )
    conn.commit()
    emit_run_event("stage_start", stage="score", run_id="run-hist")

    client = TestClient(create_app())
    r = client.get("/api/runs/run-hist/events/history")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["event_type"] == "stage_start"


def test_run_events_history(temp_db, monkeypatch):
    import uuid

    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.orchestration.events import emit_run_event, init_run_schema
    from applypilot.server.app import create_app

    run_id = f"run-hist-{uuid.uuid4().hex[:8]}"
    close_connection()
    init_db()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES (?, 'pipeline', 'completed', '2026-05-18T00:00:00+00:00')
        """,
        (run_id,),
    )
    conn.commit()
    monkeypatch.setenv("APPLYPILOT_RUN_ID", run_id)
    emit_run_event("stage_start", stage="discover", message="go")

    client = TestClient(create_app())
    r = client.get(f"/api/runs/{run_id}/events/history")
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "stage_start"


def test_start_apply_returns_stub(temp_db, monkeypatch):
    from applypilot.server.app import create_app

    def fake_start(run_type, **kwargs):
        return {
            "id": "apply-stub",
            "run_type": run_type,
            "status": "failed",
            "stages": [],
            "stream": False,
            "dry_run": False,
            "current_stage": None,
            "exit_code": None,
            "error_message": "apply runs use applypilot apply for now",
            "started_at": "2026-05-18T00:00:00+00:00",
            "finished_at": "2026-05-18T00:00:01+00:00",
        }

    monkeypatch.setattr("applypilot.server.runs.start_typed_run", fake_start, raising=False)
    client = TestClient(create_app())
    r = client.post("/api/runs", json={"run_type": "apply"})
    assert r.status_code == 200
    assert r.json()["run_type"] == "apply"
    assert r.json()["status"] == "failed"
