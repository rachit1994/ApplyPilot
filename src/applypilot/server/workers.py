"""Worker snapshots derived from run_events worker_heartbeat payloads."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from applypilot.database import get_connection
from applypilot.orchestration.events import init_run_schema
from applypilot.orchestration.run_controller import get_active_run

router = APIRouter()


def fetch_workers_for_run(run_id: str | None, *, limit: int = 500) -> tuple[list[dict[str, Any]], str | None]:
    """Latest heartbeat per worker_id for the given run."""
    if not run_id:
        return [], None
    init_run_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, payload_json, created_at
        FROM run_events
        WHERE run_id = ? AND event_type = 'worker_heartbeat'
        ORDER BY id DESC
        LIMIT ?
        """,
        (run_id, limit),
    ).fetchall()
    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        payload: dict[str, Any] = {}
        if row["payload_json"]:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = {}
        wid = payload.get("worker_id")
        if wid is None:
            continue
        try:
            iwid = int(wid)
        except (TypeError, ValueError):
            continue
        if iwid in latest:
            continue
        status = payload.get("status")
        pct: int | None = None
        if isinstance(status, str) and status.upper() == "DONE":
            pct = 100
        elif isinstance(status, str) and status.upper() in {"BUSY", "ACTIVE", "WORKING"}:
            pct = 55
        latest[iwid] = {
            "worker_id": iwid,
            "status": status if isinstance(status, str) else None,
            "detail": payload.get("detail"),
            "progress_percent": pct,
            "updated_at": row["created_at"],
        }
    ordered = sorted(latest.values(), key=lambda x: int(x["worker_id"]))
    return ordered, run_id


@router.get("/workers")
def api_workers(run_id: str | None = Query(default=None)) -> dict[str, Any]:
    rid = run_id
    if not rid:
        active = get_active_run()
        rid = active["id"] if active else None
    workers, resolved = fetch_workers_for_run(rid)
    return {"workers": workers, "run_id": resolved}


@router.get("/workers/stream")
async def api_workers_stream(run_id: str | None = Query(default=None)) -> StreamingResponse:
    import asyncio
    import json as json_lib

    rid = run_id
    if not rid:
        active = get_active_run()
        rid = active["id"] if active else None

    async def gen():
        last_json = ""
        while True:
            workers, _ = fetch_workers_for_run(rid)
            blob = json_lib.dumps({"workers": workers, "run_id": rid}, default=str)
            if blob != last_json:
                last_json = blob
                yield f"data: {blob}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
