"""Tests for pipeline stage_progress snapshots."""

from __future__ import annotations

import sqlite3

import pytest

from applypilot import database
from applypilot.pipeline import _emit_stage_progress, _stage_progress_snapshot


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "progress.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    yield db_path
    database.close_connection()
    database.invalidate_stats_cache()


def _insert_job(conn: sqlite3.Connection, url: str, **fields) -> None:
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


def test_stage_progress_snapshot_enrich(temp_db):
    conn = database.get_connection()
    _insert_job(
        conn,
        "https://a.example/j1",
        full_description="x",
        detail_scraped_at="2026-05-18T00:00:00+00:00",
    )
    _insert_job(conn, "https://a.example/j2")

    snap = _stage_progress_snapshot("enrich")
    assert snap["done"] == 1
    assert snap["pending"] == 1
    assert snap["percent"] == 50
    assert "1/2" in snap["detail"]


def test_stage_progress_snapshot_filter(temp_db):
    conn = database.get_connection()
    _insert_job(
        conn,
        "https://a.example/kept",
        pre_fit_score=8,
        detail_scraped_at="2026-05-18T00:00:00+00:00",
    )
    _insert_job(
        conn,
        "https://a.example/rejected",
        pre_fit_score=1,
        pre_filter_reason="title:junior_or_intern",
        pre_filter_rejected_at="2026-05-18T00:00:00+00:00",
        fit_score=1,
        detail_scraped_at="2026-05-18T00:00:00+00:00",
    )
    _insert_job(
        conn,
        "https://a.example/pending",
        detail_scraped_at="2026-05-18T00:00:00+00:00",
    )

    snap = _stage_progress_snapshot("filter")
    assert snap["done"] == 2
    assert snap["pending"] == 1
    assert snap["percent"] == 67
    assert "1 kept" in snap["detail"]
    assert "1 rejected" in snap["detail"]


def test_stage_progress_snapshot_score(temp_db):
    conn = database.get_connection()
    _insert_job(conn, "https://a.example/j1", full_description="x", fit_score=8)
    _insert_job(conn, "https://a.example/j2", full_description="y")

    snap = _stage_progress_snapshot("score")
    assert snap["done"] == 1
    assert snap["pending"] == 1
    assert snap["percent"] == 50


def test_emit_stage_progress_with_run(monkeypatch, temp_db):
    from applypilot.orchestration import events

    conn = database.get_connection()
    events.init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, started_at)
        VALUES ('run-prog', 'pipeline', 'running', '2026-05-18T00:00:00+00:00')
        """
    )
    conn.commit()

    monkeypatch.setenv("APPLYPILOT_RUN_ID", "run-prog")
    event = _emit_stage_progress("discover")
    assert event is not None
    assert event["event_type"] == "stage_progress"
    assert event["stage"] == "discover"
    assert "JobSpy" in event["message"]
