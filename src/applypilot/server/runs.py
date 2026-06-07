"""Run control API routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException

from applypilot.orchestration.run_controller import (
    get_active_run,
    get_run,
    list_runs,
    start_typed_run,
    stop_run,
)
from applypilot.server.schemas import RunResponse, StartRunRequest

router = APIRouter()


def _check_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("APPLYPILOT_DASHBOARD_TOKEN", "").strip()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


def _to_response(run: dict) -> RunResponse:
    return RunResponse(**run)


@router.get("/runs", response_model=list[RunResponse])
def api_list_runs(limit: int = 50) -> list[RunResponse]:
    """Recent runs newest-first, with event_count and last log line for the dashboard list."""
    return [_to_response(r) for r in list_runs(limit=min(limit, 100))]


@router.get("/runs/active", response_model=RunResponse | None)
def api_active_run() -> RunResponse | None:
    run = get_active_run()
    return _to_response(run) if run else None


@router.get("/runs/{run_id}", response_model=RunResponse)
def api_get_run(run_id: str) -> RunResponse:
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_response(run)


@router.post("/runs", response_model=RunResponse)
def api_start_run(
    body: StartRunRequest,
    authorization: str | None = Header(default=None),
) -> RunResponse:
    _check_token(authorization)
    try:
        run = start_typed_run(
            body.run_type,
            stages=body.stages,
            stream=body.stream,
            dry_run=body.dry_run,
            min_score=body.min_score,
            workers=body.workers,
            validation_mode=body.validation_mode,
            force=body.force,
            limit=body.limit,
            watch=body.watch,
            pace=body.pace,
            headless=body.headless,
            continuous=body.continuous,
            prepare=body.prepare,
            staged_only=body.staged_only,
            inbox_action=body.inbox_action,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _to_response(run)


@router.post("/runs/{run_id}/stop", response_model=RunResponse)
def api_stop_run(
    run_id: str,
    authorization: str | None = Header(default=None),
) -> RunResponse:
    _check_token(authorization)
    return _to_response(stop_run(run_id))
