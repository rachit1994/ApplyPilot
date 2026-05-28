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
        from applypilot import config
        from applypilot import database
        from applypilot.orchestration import events

        config.load_env()
        monkeypatch.setattr(config, "APP_DIR", Path(tmp))
        monkeypatch.setattr(config, "DB_PATH", db)
        monkeypatch.setattr(database, "DB_PATH", db)
        monkeypatch.setattr(events, "DB_PATH", db)
        database.close_connection()
        yield db
        database.close_connection(db)


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
    assert stats["priority_boards"] == ["LinkedIn", "Wellfound"]
    assert "LinkedIn" in stats["apply_queue_order"]
    assert "scored" in stats["pipeline"]

    r2 = client.get("/api/meta/stages")
    assert r2.status_code == 200
    assert "discover" in r2.json()["order"]


def test_api_overview_smoke(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, location, salary, fit_score, full_description, discovered_at)
        VALUES
          ('https://a.example/j1', 'Engineer', 'Acme', 'Remote', '$100k', 8, 'desc', '2026-05-18T10:00:00+00:00'),
          ('https://a.example/j2', 'Engineer 2', 'Beta', 'NYC', '$120k', 6, 'desc', '2026-05-18T11:00:00+00:00')
        """
    )
    conn.commit()

    client = TestClient(create_app())
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert "runband" in body
    assert "kpis" in body
    assert "funnel" in body
    assert "score_distribution" in body
    assert isinstance(body["top_opportunities"], list)


def test_api_activity_and_workers_smoke(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.orchestration.events import emit_run_event, init_run_schema
    from applypilot.server.activity import emit_dashboard_activity
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES ('run-activity', 'pipeline', 'running', '2026-05-18T00:00:00+00:00')
        """
    )
    conn.commit()

    emit_dashboard_activity("hello", stage="discover", run_id="run-activity")
    emit_run_event(
        "worker_heartbeat",
        run_id="run-activity",
        payload={"worker_id": 1, "status": "BUSY", "detail": "working"},
    )

    client = TestClient(create_app())
    r1 = client.get("/api/activity", params={"limit": 5})
    assert r1.status_code == 200
    assert len(r1.json()["events"]) >= 1

    r2 = client.get("/api/workers", params={"run_id": "run-activity"})
    assert r2.status_code == 200
    assert r2.json()["run_id"] == "run-activity"
    assert isinstance(r2.json()["workers"], list)

def test_api_source_stats_rollup(temp_db):
    from applypilot.database import get_connection, init_db, record_discover_source_stats
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    record_discover_source_stats(
        conn,
        source="remoteok",
        run_id="run-source",
        discovered=10,
        passed_filter=6,
        created_at="2026-05-26T00:00:00+00:00",
    )
    conn.execute(
        """
        UPDATE discover_source_stats
        SET scored_ge7 = 3, tailored = 2
        WHERE source = 'remoteok'
        """
    )
    conn.commit()

    client = TestClient(create_app())
    response = client.get("/api/source-stats")
    assert response.status_code == 200
    rows = response.json()["sources"]
    assert rows[0]["source"] == "remoteok"
    assert rows[0]["discovered"] == 10
    assert rows[0]["passed_filter"] == 6
    assert rows[0]["scored_ge7"] == 3
    assert rows[0]["tailored"] == 2
    assert rows[0]["efficiency"] == 0.3


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


def test_api_jobs_search_escapes_like_wildcards(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, fit_score, discovered_at)
        VALUES
          ('https://a.example/j1', '100% remote', 'Acme', 8, '2026-05-18T10:00:00+00:00'),
          ('https://b.example/j2', 'Onsite only', 'Beta', 5, '2026-05-18T11:00:00+00:00')
        """
    )
    conn.commit()

    client = TestClient(create_app())
    # Literal % must not match every row (unescaped LIKE would return both).
    assert client.get("/api/jobs", params={"search": "%"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"search": "100%"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"search": "Onsite"}).json()["total"] == 1


def test_api_jobs_stage_filter_and_columns(temp_db):
    from applypilot.database import get_connection, init_db
    from applypilot.server.app import create_app

    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, fit_score, discovered_at,
            tailored_resume_path, cover_letter_path, apply_status
        )
        VALUES
          ('https://a.example/ready', 'Ready Role', 'Acme', 8,
           '2026-05-18T10:00:00+00:00', '/tmp/resume.pdf', NULL, NULL),
          ('https://a.example/scored', 'Scored Role', 'Acme', 7,
           '2026-05-18T11:00:00+00:00', NULL, NULL, NULL)
        """
    )
    conn.commit()

    client = TestClient(create_app())
    ready = client.get("/api/jobs", params={"stage": "ready"})
    assert ready.status_code == 200
    body = ready.json()
    assert body["total"] == 1
    job = body["jobs"][0]
    assert job["url"] == "https://a.example/ready"
    assert job["tailored_resume_path"] == "/tmp/resume.pdf"
    assert "application_url" in job
    assert "cover_letter_at" in job
    assert "apply_error" in job

    scored = client.get("/api/jobs", params={"stage": "scored"})
    assert scored.json()["total"] == 1
    assert scored.json()["jobs"][0]["url"] == "https://a.example/scored"

    discovered = client.get("/api/jobs", params={"stage": "discovered"})
    assert discovered.json()["total"] == 0

    unknown = client.get("/api/jobs", params={"stage": "not_a_real_stage"})
    assert unknown.json()["total"] == 0


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


def test_start_apply_run(temp_db, monkeypatch):
    from applypilot.server.app import create_app

    def fake_start(run_type, **kwargs):
        return {
            "id": "apply-test-id",
            "run_type": run_type,
            "status": "running",
            "stages": [],
            "stream": False,
            "dry_run": False,
            "current_stage": "apply",
            "exit_code": None,
            "error_message": None,
            "started_at": "2026-05-18T00:00:00+00:00",
            "finished_at": None,
        }

    monkeypatch.setattr("applypilot.server.runs.start_typed_run", fake_start, raising=False)
    client = TestClient(create_app())
    r = client.post(
        "/api/runs",
        json={"run_type": "apply", "min_score": 7, "workers": 1, "watch": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["run_type"] == "apply"
    assert body["status"] == "running"


def test_inbox_queue_endpoint(temp_db):
    from applypilot.server.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/inbox/queue?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert "queue" in data
    assert "stats" in data


def test_applications_api_surfaces_submitted_unverified(temp_db):
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.server.app import create_app

    close_connection()
    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, tailored_resume_path, apply_status, apply_error,
            applied_at, last_attempted_at, application_url
        )
        VALUES
          (
            'https://jobs.example/applied', 'Verified Engineer', 'Example',
            '/tmp/resume-a.pdf', 'applied', NULL,
            '2026-05-18T10:00:00+00:00', '2026-05-18T10:00:00+00:00',
            'https://jobs.example/applied/apply'
          ),
          (
            'https://jobs.example/unverified', 'Needs Review', 'Example',
            '/tmp/resume-u.pdf', 'submitted_unverified',
            'legacy RESULT:APPLIED without structured proof',
            '2026-05-18T11:00:00+00:00', '2026-05-18T11:00:00+00:00',
            'https://jobs.example/unverified/apply'
          ),
          (
            'https://jobs.example/retry', 'Retry Me', 'Example',
            '/tmp/resume-r.pdf', 'submitted_unverified',
            'post-submit proof missing',
            '2026-05-18T12:00:00+00:00', '2026-05-18T12:00:00+00:00',
            'https://jobs.example/retry/apply'
          ),
          (
            'https://jobs.example/failed', 'Failed Engineer', 'Example',
            '/tmp/resume-f.pdf', 'failed', 'captcha',
            NULL, '2026-05-18T13:00:00+00:00',
            'https://jobs.example/failed/apply'
          )
        """
    )
    conn.commit()

    client = TestClient(create_app())
    apps = client.get("/api/applications")
    assert apps.status_code == 200
    body = apps.json()
    assert body["total"] == 3
    statuses = {row["url"]: row["apply_status"] for row in body["applications"]}
    assert statuses["https://jobs.example/applied"] == "applied"
    assert statuses["https://jobs.example/unverified"] == "submitted_unverified"
    assert "https://jobs.example/failed" not in statuses

    stats = client.get("/api/stats").json()["stats"]
    assert stats["applied"] == 1
    assert stats["pipeline"]["submitted_unverified"] == 2

    applied_jobs = client.get(
        "/api/jobs",
        params={"pipeline_stage": "applied"},
    ).json()
    assert applied_jobs["total"] == 1
    assert applied_jobs["jobs"][0]["url"] == "https://jobs.example/applied"

    needs_check_jobs = client.get(
        "/api/jobs",
        params={"stage": "needs_check"},
    ).json()
    assert needs_check_jobs["total"] == 2
    assert {
        row["url"] for row in needs_check_jobs["jobs"]
    } == {
        "https://jobs.example/unverified",
        "https://jobs.example/retry",
    }

    confirm = client.post(
        "/api/applications/confirm",
        params={"url": "https://jobs.example/unverified"},
    )
    assert confirm.status_code == 200
    confirmed = conn.execute(
        """
        SELECT apply_status, apply_error, applied_at, verification_confidence
        FROM jobs WHERE url = 'https://jobs.example/unverified'
        """
    ).fetchone()
    assert confirmed["apply_status"] == "applied"
    assert confirmed["apply_error"] is None
    assert confirmed["applied_at"] is not None
    assert confirmed["verification_confidence"] == "human_confirmed"

    retry = client.post(
        "/api/applications/retry",
        params={"url": "https://jobs.example/retry"},
    )
    assert retry.status_code == 200
    retried = conn.execute(
        """
        SELECT apply_status, apply_error, applied_at
        FROM jobs WHERE url = 'https://jobs.example/retry'
        """
    ).fetchone()
    assert retried["apply_status"] is None
    assert retried["apply_error"] is None
    assert retried["applied_at"] is None


def test_application_actions_preserve_percent_encoded_urls(temp_db):
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.server.app import create_app

    close_connection()
    init_db()
    conn = get_connection()
    encoded_url = "https://jobs.example/apply?candidate=a%2Bb&source=jobs%252Ffeed"
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, tailored_resume_path, apply_status, apply_error,
            applied_at, last_attempted_at, application_url
        )
        VALUES (?, 'Encoded URL', 'Example', '/tmp/resume.pdf',
                'submitted_unverified', 'post-submit proof missing',
                '2026-05-18T12:00:00+00:00', '2026-05-18T12:00:00+00:00', ?)
        """,
        (encoded_url, encoded_url),
    )
    conn.commit()

    client = TestClient(create_app())
    detail = client.get("/api/applications/detail", params={"url": encoded_url})
    assert detail.status_code == 200
    assert detail.json()["application"]["url"] == encoded_url

    confirm = client.post("/api/applications/confirm", params={"url": encoded_url})
    assert confirm.status_code == 200
    confirmed = conn.execute(
        "SELECT apply_status FROM jobs WHERE url = ?", (encoded_url,)
    ).fetchone()
    assert confirmed["apply_status"] == "applied"

    conn.execute(
        "UPDATE jobs SET apply_status = 'submitted_unverified', apply_error = 'retry me' WHERE url = ?",
        (encoded_url,),
    )
    conn.commit()

    retry = client.post("/api/applications/retry", params={"url": encoded_url})
    assert retry.status_code == 200
    retried = conn.execute(
        "SELECT apply_status, apply_error, applied_at FROM jobs WHERE url = ?",
        (encoded_url,),
    ).fetchone()
    assert retried["apply_status"] is None
    assert retried["apply_error"] is None
    assert retried["applied_at"] is None


def test_applications_list_status_filter_and_include_failed(temp_db):
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.server.app import create_app

    close_connection()
    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, tailored_resume_path, apply_status, apply_error)
        VALUES
          ('https://jobs.example/ok', 'Ok', 'Example', '/tmp/r.pdf', 'applied', NULL),
          ('https://jobs.example/bad', 'Bad', 'Example', '/tmp/r.pdf', 'failed', 'captcha')
        """
    )
    conn.commit()

    client = TestClient(create_app())
    default = client.get("/api/applications")
    assert default.status_code == 200
    assert default.json()["total"] == 1

    with_failed = client.get("/api/applications", params={"include_failed": "true"})
    assert with_failed.status_code == 200
    assert with_failed.json()["total"] == 2

    failed_only = client.get("/api/applications", params={"status": "failed"})
    assert failed_only.status_code == 200
    assert failed_only.json()["total"] == 1
    assert failed_only.json()["applications"][0]["apply_status"] == "failed"


def test_application_detail_includes_parsed_verification(temp_db):
    from applypilot import config
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.server.app import create_app

    close_connection()
    init_db()
    log_dir = config.APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "claude_test_detail.txt"
    log_path.write_text(
        """
>> browser_fill email user@example.com
browser snapshot {"fieldCount": 1, "url": "https://jobs.example/apply", "fields": [
  {"label": "Email", "value": "user@example.com", "type": "text", "empty": false}
], "visibleErrors": [], "emptyRequired": []}
>> browser_click submit-ref Submit
RESULT_JSON:{"status":"applied","submit_click_ref":"submit-ref","submit_button_text":"Submit","pre_submit_url":"https://jobs.example/apply","post_submit_url":"https://jobs.example/thanks","post_submit_snapshot":{"fieldCount":0,"fields":[]},"confirmation_copy":"Application received"}
""",
        encoding="utf-8",
    )

    job_url = "https://jobs.example/detail-job"
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (
            url, title, site, tailored_resume_path, apply_status,
            apply_log_path, applied_at, last_attempted_at
        )
        VALUES (?, 'Detail Job', 'Example', '/tmp/r.pdf', 'applied', ?, '2026-05-18T10:00:00+00:00',
                '2026-05-18T10:00:00+00:00')
        """,
        (job_url, str(log_path)),
    )
    conn.commit()

    client = TestClient(create_app())
    detail = client.get("/api/applications/detail", params={"url": job_url})
    assert detail.status_code == 200
    parsed = detail.json()["application"]["log_detail"]["parsed"]
    assert parsed is not None
    assert parsed["result_json"]["status"] == "applied"
    assert parsed["verification"]["decision"] == "verified"
    assert len(parsed["fields"]) == 1
    assert parsed["fields"][0]["label"] == "Email"
    form_filled = detail.json()["application"]["form_filled"]
    assert form_filled is not None
    assert form_filled["field_count"] >= 1
    assert form_filled["fields"][0]["label"] == "Email"
    assert form_filled["fields"][0]["value"] == "user@example.com"


def test_application_detail_backfills_form_filled_from_log(temp_db):
    from applypilot import config
    from applypilot.database import close_connection, get_connection, init_db
    from applypilot.server.app import create_app

    close_connection()
    init_db()
    log_dir = config.APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "claude_backfill_form.txt"
    log_path.write_text(
        ">> browser_fill textarea message Draft note\n"
        'browser snapshot {"fieldCount": 0, "fields": [], "visibleErrors": [], "emptyRequired": 0}\n'
        'RESULT_JSON:{"status":"failed","reason":"captcha"}\n',
        encoding="utf-8",
    )
    job_url = "https://jobs.example/backfill-form"
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, tailored_resume_path, apply_status, apply_log_path)
        VALUES (?, 'Backfill', 'Example', '/tmp/r.pdf', 'failed', ?)
        """,
        (job_url, str(log_path)),
    )
    conn.commit()

    client = TestClient(create_app())
    detail = client.get("/api/applications/detail", params={"url": job_url})
    assert detail.status_code == 200
    form_filled = detail.json()["application"]["form_filled"]
    assert form_filled is not None
    assert any(f["label"] == "textarea message" for f in form_filled["fields"])

    row = conn.execute(
        "SELECT apply_form_filled FROM jobs WHERE url = ?", (job_url,)
    ).fetchone()
    assert row[0] is not None
