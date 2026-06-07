"""SSE event streaming for dashboard runs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from applypilot.orchestration.events import list_run_events, subscribe_run_events, unsubscribe_run_events
from applypilot.orchestration.run_controller import get_run

router = APIRouter()

_ACTIVE_STATUSES = frozenset({"running", "starting"})
_POLL_INTERVAL_SEC = 1.0


def _format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, default=str)
    return f"data: {data}\n\n"


def collect_new_db_events(
    run_id: str,
    last_id: int,
    sent_ids: set[int],
) -> tuple[list[dict[str, Any]], int, bool]:
    """Fetch persisted events not yet sent (subprocess writes bypass in-memory subscribers)."""
    out: list[dict[str, Any]] = []
    finished = False
    for event in list_run_events(run_id, after_id=last_id):
        eid = int(event["id"])
        if eid in sent_ids:
            continue
        sent_ids.add(eid)
        last_id = max(last_id, eid)
        out.append(event)
        if event.get("event_type") == "run_finished":
            finished = True
    return out, last_id, finished


def _prepare_queue_event(
    event: dict[str, Any],
    run_id: str,
    last_id: int,
) -> tuple[dict[str, Any], int]:
    """Normalize parent-process queue events (always have DB id after emit)."""
    if event.get("id"):
        return event, max(last_id, int(event["id"]))
    recent = list_run_events(run_id, after_id=last_id, limit=1)
    if recent:
        event = recent[-1]
        return event, int(event["id"])
    return event, last_id


@router.get("/runs/{run_id}/events/history")
def run_events_history(
    run_id: str,
    after_id: int = 0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Full event backlog for reconnect (SSE also polls DB while the run is active)."""
    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return list_run_events(run_id, after_id=after_id, limit=limit)


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, after_id: int = 0) -> StreamingResponse:
    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator() -> AsyncIterator[str]:
        last_id = after_id
        sent_ids: set[int] = set()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_event(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        subscribe_run_events(run_id, on_event)
        try:
            backlog, last_id, finished = collect_new_db_events(
                run_id, last_id, sent_ids
            )
            for event in backlog:
                yield _format_sse(event)
            if finished:
                return

            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_POLL_INTERVAL_SEC
                    )
                    event, last_id = _prepare_queue_event(event, run_id, last_id)
                    eid = event.get("id")
                    if eid is not None:
                        eid_int = int(eid)
                        if eid_int not in sent_ids:
                            sent_ids.add(eid_int)
                            last_id = max(last_id, eid_int)
                            yield _format_sse(event)
                            if event.get("event_type") == "run_finished":
                                break
                except asyncio.TimeoutError:
                    pass

                db_events, last_id, db_finished = collect_new_db_events(
                    run_id, last_id, sent_ids
                )
                for event in db_events:
                    yield _format_sse(event)
                if db_finished:
                    break

                run = get_run(run_id)
                if run and run["status"] not in _ACTIVE_STATUSES:
                    db_events, _, _ = collect_new_db_events(
                        run_id, last_id, sent_ids
                    )
                    for event in db_events:
                        yield _format_sse(event)
                    break
        finally:
            unsubscribe_run_events(run_id, on_event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
