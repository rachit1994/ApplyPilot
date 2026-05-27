"""Inbox queue API for the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from applypilot.inbox.db import get_inbox_stats, init_inbox_schema
from applypilot.inbox.ranker import build_ranked_queue
from applypilot.inbox.runner import run_inbox_pipeline
from applypilot.inbox.scanner import scan_inbox
from applypilot.database import get_connection
from applypilot.orchestration.run_controller import start_inbox_run
from applypilot.server.runs import _check_token

router = APIRouter()


@router.get("/inbox/queue")
def api_inbox_queue(limit: int = 50) -> dict:
    """Ranked LinkedIn Other-tab apply opportunities."""
    conn = get_connection()
    init_inbox_schema(conn)
    rows = build_ranked_queue(limit=min(limit, 200))
    stats = get_inbox_stats(conn)
    return {"queue": rows, "total": len(rows), "stats": stats}


@router.post("/inbox/scan")
def api_inbox_scan(
    limit: int | None = None,
    authorization: str | None = Header(default=None),
) -> dict:
    _check_token(authorization)
    try:
        return scan_inbox(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/inbox/run")
def api_inbox_run(
    action: str = "pipeline",
    limit: int | None = None,
    dry_run: bool = False,
    subprocess: bool = True,
    authorization: str | None = Header(default=None),
) -> dict:
    """Run inbox scan/classify/pipeline in-process or as a tracked subprocess."""
    _check_token(authorization)
    if subprocess:
        try:
            run = start_inbox_run(
                action=action,
                limit=limit,
                dry_run=dry_run,
            )
            return {"mode": "subprocess", "run": run}
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        report = run_inbox_pipeline(
            do_scan=True,
            do_classify=True,
            do_draft=True,
            do_send=False,
            limit=limit,
            dry_run=dry_run,
        )
        return {"mode": "inline", "report": report}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
