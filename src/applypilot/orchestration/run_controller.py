"""Subprocess lifecycle for dashboard-triggered ApplyPilot runs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.database import get_connection, init_db
from applypilot.orchestration.events import (
    emit_run_event,
    init_run_schema,
    list_run_events,
)
from applypilot.pipeline import STAGE_ORDER

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|secret)\s*[=:]\s*\S+",
)
_BEARER_RE = re.compile(r"(?i)Bearer\s+\S+")
_LOG_LEVEL_PREFIX = re.compile(
    r"^(?:\d{2}:\d{2}:\d{2}\s+-\s+)?(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+-\s+",
    re.IGNORECASE,
)

_active_process: subprocess.Popen[str] | None = None
_active_run_id: str | None = None
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(line: str) -> str:
    line = _SECRET_RE.sub(r"\1=***", line)
    line = _BEARER_RE.sub("Bearer ***", line)
    return line


def _resolve_cli() -> list[str]:
    """Command prefix to invoke applypilot in the current environment."""
    if shutil.which("applypilot"):
        return ["applypilot"]
    return [sys.executable, "-m", "applypilot"]


def get_active_run() -> dict[str, Any] | None:
    with _lock:
        if not _active_run_id:
            return None
        return get_run(_active_run_id)


def get_run(run_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    init_run_schema(conn)
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    stages: list[str] = []
    if row["stages_json"]:
        try:
            stages = json.loads(row["stages_json"])
        except json.JSONDecodeError:
            stages = []
    return {
        "id": row["id"],
        "run_type": row["run_type"],
        "status": row["status"],
        "stages": stages,
        "stream": bool(row["stream"]),
        "dry_run": bool(row["dry_run"]),
        "current_stage": row["current_stage"],
        "exit_code": row["exit_code"],
        "error_message": row["error_message"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_connection()
    init_run_schema(conn)
    rows = conn.execute(
        """
        SELECT
            r.*,
            (
                SELECT COUNT(*)
                FROM run_events e
                WHERE e.run_id = r.id
            ) AS event_count,
            (
                SELECT e.message
                FROM run_events e
                WHERE e.run_id = r.id
                ORDER BY e.id DESC
                LIMIT 1
            ) AS last_event_message
        FROM runs r
        ORDER BY r.started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        stages: list[str] = []
        if row["stages_json"]:
            try:
                stages = json.loads(row["stages_json"])
            except json.JSONDecodeError:
                stages = []
        out.append({
            "id": row["id"],
            "run_type": row["run_type"],
            "status": row["status"],
            "stages": stages,
            "stream": bool(row["stream"]),
            "dry_run": bool(row["dry_run"]),
            "current_stage": row["current_stage"],
            "exit_code": row["exit_code"],
            "error_message": row["error_message"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "event_count": int(row["event_count"] or 0),
            "last_event_message": row["last_event_message"],
        })
    return out


def _set_run_status(
    run_id: str,
    status: str,
    *,
    exit_code: int | None = None,
    error_message: str | None = None,
) -> None:
    conn = get_connection()
    finished = _now() if status in ("completed", "failed", "stopped") else None
    conn.execute(
        """
        UPDATE runs
        SET status = ?, exit_code = ?, error_message = ?, finished_at = COALESCE(?, finished_at)
        WHERE id = ?
        """,
        (status, exit_code, error_message, finished, run_id),
    )
    conn.commit()


def infer_log_level(line: str, stream_label: str = "stdout") -> str:
    """Map a subprocess log line to dashboard level (info / warning / error)."""
    match = _LOG_LEVEL_PREFIX.match(line)
    if match:
        token = match.group(1).upper()
        if token in ("ERROR", "CRITICAL"):
            return "error"
        if token in ("WARNING", "WARN"):
            return "warning"
        return "info"

    lowered = line.lower()
    if "error:" in lowered or re.search(r"\berror\b", lowered):
        return "error"
    if "warning" in lowered:
        return "warning"
    if stream_label == "stderr":
        return "warning"
    return "info"


def _read_stream(run_id: str, stream, label: str) -> None:
    global _active_process
    if stream is None:
        return
    for raw in stream:
        if raw is None:
            break
        line = raw.rstrip("\n")
        if not line:
            continue
        line = _redact(line)
        level = infer_log_level(line, label)
        emit_run_event("log", level=level, message=line, run_id=run_id)


def _wait_process(run_id: str, proc: subprocess.Popen[str]) -> None:
    global _active_process, _active_run_id
    try:
        code = proc.wait()
        status = "completed" if code == 0 else "failed"
        _set_run_status(run_id, status, exit_code=code)
        emit_run_event(
            "run_finished",
            run_id=run_id,
            message=status,
            payload={"exit_code": code},
            level="error" if code != 0 else "info",
        )
    except Exception as e:
        _set_run_status(run_id, "failed", error_message=str(e))
        emit_run_event(
            "run_finished",
            run_id=run_id,
            level="error",
            message=str(e),
            payload={"error": str(e)},
        )
    finally:
        with _lock:
            if _active_run_id == run_id:
                _active_process = None
                _active_run_id = None


def start_pipeline_run(
    *,
    stages: list[str] | None = None,
    stream: bool = False,
    dry_run: bool = False,
    min_score: int = 7,
    workers: int = 1,
    validation_mode: str = "normal",
    force: bool = False,
) -> dict[str, Any]:
    """Spawn applypilot run as a subprocess tracked by run_id."""
    global _active_process, _active_run_id

    init_db()
    with _lock:
        if _active_process is not None and _active_process.poll() is None:
            if not force:
                raise RuntimeError(
                    f"Run {_active_run_id} is still active. Stop it first or use force=true."
                )
            stop_run(_active_run_id or "")

    if stages is None or not stages or stages == ["all"]:
        stage_list = list(STAGE_ORDER)
    else:
        stage_list = stages

    run_id = str(uuid.uuid4())
    started = _now()
    conn = get_connection()
    init_run_schema(conn)
    conn.execute(
        """
        INSERT INTO runs (id, run_type, status, stages_json, stream, dry_run, started_at)
        VALUES (?, 'pipeline', 'running', ?, ?, ?, ?)
        """,
        (run_id, json.dumps(stage_list), int(stream), int(dry_run), started),
    )
    conn.commit()

    cmd = _resolve_cli() + ["run", *stage_list]
    if stream:
        cmd.append("--stream")
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(["--min-score", str(min_score), "--workers", str(workers)])
    cmd.extend(["--validation", validation_mode])

    env = os.environ.copy()
    env["APPLYPILOT_RUN_ID"] = run_id
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(Path.cwd()),
    )

    with _lock:
        _active_process = proc
        _active_run_id = run_id

    emit_run_event(
        "run_started",
        run_id=run_id,
        message="subprocess started",
        payload={"command": cmd, "stages": stage_list},
    )
    emit_run_event("log", run_id=run_id, message=f"$ {' '.join(cmd)}")

    threading.Thread(
        target=_read_stream, args=(run_id, proc.stdout, "stdout"), daemon=True
    ).start()
    threading.Thread(
        target=_read_stream, args=(run_id, proc.stderr, "stderr"), daemon=True
    ).start()
    threading.Thread(target=_wait_process, args=(run_id, proc), daemon=True).start()

    return get_run(run_id) or {"id": run_id, "status": "running"}


def stop_run(run_id: str) -> dict[str, Any]:
    global _active_process, _active_run_id
    with _lock:
        if _active_run_id != run_id or _active_process is None:
            run = get_run(run_id)
            if run and run["status"] == "running":
                _set_run_status(run_id, "stopped")
            return get_run(run_id) or {"id": run_id, "status": "stopped"}
        proc = _active_process
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    _set_run_status(run_id, "stopped", exit_code=proc.returncode)
    emit_run_event("run_finished", run_id=run_id, message="stopped", level="warning")
    with _lock:
        _active_process = None
        _active_run_id = None
    return get_run(run_id) or {"id": run_id, "status": "stopped"}


def start_typed_run(
    run_type: str,
    *,
    stages: list[str] | None = None,
    stream: bool = False,
    dry_run: bool = False,
    force: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch run by type (pipeline v1; apply/refer/inbox phase 2)."""
    if run_type == "pipeline":
        return start_pipeline_run(
            stages=stages,
            stream=stream,
            dry_run=dry_run,
            force=force,
            **kwargs,
        )
    if run_type in ("apply", "refer", "inbox"):
        run_id = str(uuid.uuid4())
        started = _now()
        conn = get_connection()
        init_run_schema(conn)
        conn.execute(
            """
            INSERT INTO runs (id, run_type, status, stages_json, stream, dry_run, started_at)
            VALUES (?, ?, 'failed', ?, ?, ?, ?)
            """,
            (
                run_id,
                run_type,
                json.dumps(stages or []),
                int(stream),
                int(dry_run),
                started,
            ),
        )
        conn.commit()
        msg = f"{run_type} dashboard control is not implemented yet; use CLI for now."
        _set_run_status(run_id, "failed", error_message=msg)
        os.environ["APPLYPILOT_RUN_ID"] = run_id
        try:
            emit_run_event("run_started", run_id=run_id, message=msg)
            emit_run_event("log", run_id=run_id, level="error", message=msg)
            emit_run_event("run_finished", run_id=run_id, level="error", message="failed")
        finally:
            os.environ.pop("APPLYPILOT_RUN_ID", None)
        return get_run(run_id) or {"id": run_id, "status": "failed", "error_message": msg}
    raise ValueError(f"Unknown run_type: {run_type}")
