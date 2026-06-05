"""Active run detection: DB fallback and reconcile after serve reload."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from applypilot import database
from applypilot.orchestration.events import emit_run_event, init_run_schema


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "active_run.db"
    monkeypatch.setenv("APPLYPILOT_DIR", str(tmp_path))
    from applypilot import config

    config.load_env()
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.close_connection()
    database.init_db()
    yield db_path
    database.close_connection()


def _insert_running_run(conn, run_id: str = "run-db") -> None:
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (
            id, run_type, status, stages_json, stream, dry_run,
            started_at, current_stage
        )
        VALUES (?, 'pipeline', 'running', '["discover"]', 0, 0, ?, 'discover')
        """,
        (run_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def test_get_active_run_falls_back_to_db_without_memory_handle(temp_db):
    import applypilot.orchestration.run_controller as rc

    conn = database.get_connection()
    _insert_running_run(conn, "run-db-only")
    rc._active_run_id = None
    rc._active_process = None

    run = rc.get_active_run()
    assert run is not None
    assert run["id"] == "run-db-only"
    assert run["status"] == "running"
    assert run["current_stage"] == "discover"


def test_subprocess_env_prepends_local_tool_paths(monkeypatch):
    import applypilot.orchestration.run_controller as rc

    monkeypatch.setenv("PATH", "/bin")

    env = rc._subprocess_env("run-path")
    parts = env["PATH"].split(":")

    assert env["APPLYPILOT_RUN_ID"] == "run-path"
    assert parts[:3] == [
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    assert parts[-1] == "/bin"


def test_reconcile_keeps_running_run_with_recent_events(temp_db, monkeypatch):
    import applypilot.orchestration.run_controller as rc

    conn = database.get_connection()
    _insert_running_run(conn, "run-live")
    monkeypatch.setenv("APPLYPILOT_RUN_ID", "run-live")
    emit_run_event("stage_start", stage="discover", message="discover started")
    rc._active_run_id = None
    rc._active_process = None

    stopped = rc.reconcile_orphaned_runs()
    assert stopped == 0
    run = rc.get_run("run-live")
    assert run is not None
    assert run["status"] == "running"


def test_reconcile_stops_stale_running_without_events(temp_db):
    import applypilot.orchestration.run_controller as rc

    conn = database.get_connection()
    _insert_running_run(conn, "run-stale")
    rc._active_run_id = None
    rc._active_process = None

    stopped = rc.reconcile_orphaned_runs()
    assert stopped == 1
    run = rc.get_run("run-stale")
    assert run is not None
    assert run["status"] == "stopped"


def test_reconcile_stops_running_when_last_event_is_old(temp_db, monkeypatch):
    import applypilot.orchestration.run_controller as rc

    conn = database.get_connection()
    _insert_running_run(conn, "run-old")
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    conn.execute(
        """
        INSERT INTO run_events (run_id, event_type, stage, level, message, created_at)
        VALUES ('run-old', 'log', NULL, 'info', 'old line', ?)
        """,
        (old_ts,),
    )
    conn.commit()
    rc._active_run_id = None
    rc._active_process = None

    stopped = rc.reconcile_orphaned_runs()
    assert stopped == 1
    assert rc.get_run("run-old")["status"] == "stopped"
