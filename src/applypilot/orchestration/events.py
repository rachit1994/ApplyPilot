"""Structured run events for the live dashboard (SQLite + in-memory subscribers)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import logging

from applypilot.config import DB_PATH, RUN_LOG_DIR, ensure_dirs
from applypilot.database import get_connection

_RUN_ID_ENV = "APPLYPILOT_RUN_ID"
_MAX_EVENTS_PER_RUN = 10_000

_subscribers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
_sub_lock = threading.Lock()

_run_loggers: dict[str, logging.Logger] = {}
_run_logger_lock = threading.Lock()


def _run_log_path(run_id: str) -> str:
    ensure_dirs()
    return str(RUN_LOG_DIR / f"{run_id}.log")


def _get_run_logger(run_id: str) -> logging.Logger:
    with _run_logger_lock:
        existing = _run_loggers.get(run_id)
        if existing:
            return existing

        logger = logging.getLogger(f"applypilot.run.{run_id}")
        logger.setLevel(logging.INFO)
        logger.propagate = False

        path = _run_log_path(run_id)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        _run_loggers[run_id] = logger
        return logger


def _append_run_log(event: dict[str, Any]) -> None:
    """Append a UI-visible devlog line to the per-run log file."""
    rid = str(event.get("run_id") or "").strip()
    if not rid:
        return

    # Match the UI developer log sources (HomePage.tsx).
    if event.get("event_type") not in (
        "log",
        "stage_error",
        "run_started",
        "run_finished",
        "stage_start",
        "stage_end",
    ):
        return

    created_at = str(event.get("created_at") or "")
    level = str(event.get("level") or "info").upper()
    stage = str(event.get("stage") or "-")
    message = str(event.get("message") or "").rstrip("\n")
    line = f"[{created_at}] {level:<7} {stage:<10} {message}".rstrip()

    try:
        _get_run_logger(rid).info(line)
    except Exception:
        # Logging must never break the dashboard event pipeline.
        pass


def get_active_run_id() -> str | None:
    """Return run id from env when pipeline is launched by the dashboard."""
    value = os.environ.get(_RUN_ID_ENV, "").strip()
    return value or None


def init_run_schema(conn: sqlite3.Connection | None = None) -> None:
    """Create runs and run_events tables (idempotent)."""
    if conn is None:
        conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id              TEXT PRIMARY KEY,
            run_type        TEXT NOT NULL DEFAULT 'pipeline',
            status          TEXT NOT NULL DEFAULT 'starting',
            stages_json     TEXT,
            stream          INTEGER NOT NULL DEFAULT 0,
            dry_run         INTEGER NOT NULL DEFAULT 0,
            current_stage   TEXT,
            exit_code       INTEGER,
            error_message   TEXT,
            started_at      TEXT NOT NULL,
            finished_at     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            stage           TEXT,
            level           TEXT,
            message         TEXT,
            payload_json    TEXT,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id, id)"
    )
    conn.commit()


def subscribe_run_events(run_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
    """Register an in-process subscriber (used by SSE broadcaster)."""
    with _sub_lock:
        _subscribers.setdefault(run_id, []).append(callback)


def unsubscribe_run_events(run_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
    with _sub_lock:
        subs = _subscribers.get(run_id, [])
        if callback in subs:
            subs.remove(callback)
        if not subs:
            _subscribers.pop(run_id, None)


def _notify_subscribers(event: dict[str, Any]) -> None:
    run_id = event.get("run_id")
    if not run_id:
        return
    with _sub_lock:
        callbacks = list(_subscribers.get(run_id, []))
    for cb in callbacks:
        try:
            cb(event)
        except Exception:
            pass


def emit_run_event(
    event_type: str,
    *,
    stage: str | None = None,
    level: str = "info",
    message: str = "",
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Persist and broadcast a run event. No-op without run_id (plain CLI)."""
    rid = run_id or get_active_run_id()
    if not rid:
        return None

    now = datetime.now(timezone.utc).isoformat()
    event: dict[str, Any] = {
        "run_id": rid,
        "event_type": event_type,
        "stage": stage,
        "level": level,
        "message": message,
        "payload": payload or {},
        "created_at": now,
    }

    conn = get_connection()
    init_run_schema(conn)
    count = conn.execute(
        "SELECT COUNT(*) FROM run_events WHERE run_id = ?", (rid,)
    ).fetchone()[0]
    if count >= _MAX_EVENTS_PER_RUN:
        return event

    payload_json = json.dumps(payload) if payload else None
    cur = conn.execute(
        """
        INSERT INTO run_events (run_id, event_type, stage, level, message, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rid, event_type, stage, level, message, payload_json, now),
    )
    event["id"] = cur.lastrowid
    # Keep stage name on stage_end until the next stage_start (UI stepper + GET /runs poll).
    if stage and event_type in ("stage_start", "stage_end", "stage_error"):
        conn.execute(
            "UPDATE runs SET current_stage = ? WHERE id = ?",
            (stage, rid),
        )
    conn.commit()

    _append_run_log(event)
    _notify_subscribers(event)
    if event_type in ("log", "stage_error", "run_started", "run_finished", "stage_start", "stage_end"):
        try:
            from applypilot.server.activity import emit_dashboard_activity

            emit_dashboard_activity(
                message,
                level=level,
                stage=stage,
                run_id=rid,
            )
        except Exception:
            pass
    return event


def list_run_events(
    run_id: str,
    *,
    after_id: int = 0,
    limit: int = 500,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch events for SSE catch-up or polling."""
    conn = get_connection(db_path or DB_PATH)
    init_run_schema(conn)
    rows = conn.execute(
        """
        SELECT id, run_id, event_type, stage, level, message, payload_json, created_at
        FROM run_events
        WHERE run_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (run_id, after_id, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload: dict[str, Any] = {}
        if row["payload_json"]:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = {}
        out.append({
            "id": row["id"],
            "run_id": row["run_id"],
            "event_type": row["event_type"],
            "stage": row["stage"],
            "level": row["level"],
            "message": row["message"] or "",
            "payload": payload,
            "created_at": row["created_at"],
        })
    return out
