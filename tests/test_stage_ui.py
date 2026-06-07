"""Streaming run UI stage resolution."""

from __future__ import annotations

from applypilot import database
from applypilot.db.connection import Connection
from applypilot.orchestration.run_controller import get_run
from applypilot.orchestration.stage_ui import effective_current_stage


def _insert_job(conn: Connection, url: str, **fields) -> None:
    cols = ["url", "title", "site"]
    vals = [url, fields.pop("title", "Engineer"), fields.pop("site", "test")]
    for k, v in fields.items():
        cols.append(k)
        vals.append(v)
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()


def test_effective_current_stage_ignores_idle_cover_marker():
    conn = database.get_connection()
    _insert_job(
        conn,
        "https://a.example/enriched",
        full_description="done",
        detail_scraped_at="2026-05-18T00:00:00+00:00",
    )
    _insert_job(conn, "https://a.example/pending")

    from applypilot.orchestration.events import init_run_schema

    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (
            id, run_type, status, stages_json, stream, dry_run, started_at, current_stage
        )
        VALUES (
            'run-stream', 'pipeline', 'running',
            '["enrich","filter","score","tailor","pdf","cover"]',
            1, 0, '2026-05-18T00:00:00+00:00', 'cover'
        )
        """
    )
    conn.commit()

    stage = effective_current_stage(
        stream=True,
        running=True,
        db_current_stage="cover",
        run_stages=["enrich", "filter", "score", "tailor", "pdf", "cover"],
        run_id="run-stream",
    )
    assert stage == "enrich"

    run = get_run("run-stream")
    assert run is not None
    assert run["current_stage"] == "enrich"


def test_overview_stepper_marks_enrich_active_during_stream():
    conn = database.get_connection()
    _insert_job(
        conn,
        "https://a.example/enriched",
        full_description="done",
        detail_scraped_at="2026-05-18T00:00:00+00:00",
    )
    _insert_job(conn, "https://a.example/pending")

    from applypilot.orchestration.events import init_run_schema
    import applypilot.orchestration.run_controller as rc

    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (
            id, run_type, status, stages_json, stream, dry_run, started_at, current_stage
        )
        VALUES (
            'run-stream', 'pipeline', 'running',
            '["enrich","cover"]',
            1, 0, '2026-05-18T00:00:00+00:00', 'cover'
        )
        """
    )
    conn.commit()

    rc._active_run_id = "run-stream"
    rc._active_process = None

    from applypilot.server.overview import build_overview

    overview = build_overview()
    steps = {s["id"]: s for s in overview["runband"]["steps"]}
    assert steps["enrich"]["state"] == "active"
    assert steps["cover"]["state"] != "active"
    assert overview["runband"]["current_stage"] == "enrich"
