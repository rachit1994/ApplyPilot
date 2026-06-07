"""Dashboard-wide activity log (Postgres + SSE)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from applypilot.database import get_connection, init_db

router = APIRouter()

_POLL_INTERVAL_SEC = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_dashboard_activity(
    message: str,
    *,
    level: str = "info",
    stage: str | None = None,
    run_id: str | None = None,
    job_url: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int | None:
    """Persist one dashboard activity row. Safe to call from pipeline/apply code."""
    init_db()
    conn = get_connection()
    meta_json = json.dumps(meta, default=str) if meta else None
    cur = conn.execute(
        """
        INSERT INTO dashboard_activity_events (
            ts, level, stage, message, run_id, job_url, meta_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (_now_iso(), level, stage, message, run_id, job_url, meta_json),
    )
    conn.commit()
    return int(cur.lastrowid) if cur.lastrowid else None


def _row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if row["meta_json"]:
        try:
            meta = json.loads(row["meta_json"])
        except json.JSONDecodeError:
            meta = {}
    return {
        "id": int(row["id"]),
        "ts": row["ts"],
        "level": row["level"] or "info",
        "stage": row["stage"],
        "message": row["message"] or "",
        "run_id": row["run_id"],
        "job_url": row["job_url"],
        "meta": meta,
    }


def list_dashboard_activity(
    *,
    limit: int = 50,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    init_db()
    conn = get_connection()
    limit = max(1, min(limit, 500))
    if before_id is not None and before_id > 0:
        rows = conn.execute(
            """
            SELECT id, ts, level, stage, message, run_id, job_url, meta_json
            FROM dashboard_activity_events
            WHERE id < ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (before_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, ts, level, stage, message, run_id, job_url, meta_json
            FROM dashboard_activity_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_item(row) for row in rows]


def iter_dashboard_activity_after(after_id: int, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, ts, level, stage, message, run_id, job_url, meta_json
        FROM dashboard_activity_events
        WHERE id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (after_id, min(limit, 500)),
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def _format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, default=str)
    return f"data: {data}\n\n"


@router.get("/activity")
def api_dashboard_activity(limit: int = 50, before_id: int | None = None) -> dict[str, Any]:
    events = list_dashboard_activity(limit=limit, before_id=before_id)
    return {"events": events}


@router.get("/activity/stream")
async def stream_dashboard_activity(after_id: int = 0) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        last_id = after_id
        while True:
            batch = iter_dashboard_activity_after(last_id, limit=100)
            for event in batch:
                last_id = max(last_id, int(event["id"]))
                yield _format_sse(event)
            await asyncio.sleep(_POLL_INTERVAL_SEC)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
