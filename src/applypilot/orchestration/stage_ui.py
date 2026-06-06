"""Map pipeline run state to Mission Control stepper (streaming-safe)."""

from __future__ import annotations

import json
from typing import Any

from applypilot.database import get_connection
from applypilot.orchestration.events import init_run_schema
from applypilot.pipeline import _stage_progress_snapshot

# Mission Control stepper order (see overview._ui_step_index_for_stage).
UI_STEP_STAGES: tuple[str, ...] = (
    "discover",
    "enrich",
    "filter",
    "score",
    "tailor",
    "cover",
)


def latest_stage_progress_map(run_id: str) -> dict[str, dict[str, Any]]:
    """Latest stage_progress payload per stage for a run."""
    init_run_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT stage, payload_json, message, id
        FROM run_events
        WHERE run_id = ? AND event_type = 'stage_progress' AND stage IS NOT NULL
        ORDER BY id DESC
        LIMIT 800
        """,
        (run_id,),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        st = row["stage"]
        if not st or st in out:
            continue
        pl: dict[str, Any] = {}
        if row["payload_json"]:
            try:
                pl = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                pl = {}
        out[st] = {"payload": pl, "message": row["message"]}
    return out


def _pending_for_stage(
    stage: str,
    *,
    min_score: int,
    progress_map: dict[str, dict[str, Any]],
) -> int:
    live = (progress_map.get(stage) or {}).get("payload") or {}
    pending = live.get("pending")
    if pending is not None:
        return int(pending)
    snap = _stage_progress_snapshot(stage, min_score)
    return int(snap.get("pending") or 0)


def effective_current_stage(
    *,
    stream: bool,
    running: bool,
    db_current_stage: str | None,
    run_stages: list[str] | None,
    min_score: int = 7,
    run_id: str | None = None,
    progress_map: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Stage the UI should highlight as active.

    Sequential runs use runs.current_stage from the last stage_start/end event.
    Streaming runs start every stage thread at once; idle downstream stages must
    not overwrite the marker when enrich (or score) still has pending work.
    """
    if not running:
        return db_current_stage
    if not stream:
        return db_current_stage

    pmap = progress_map
    if pmap is None and run_id:
        pmap = latest_stage_progress_map(run_id)

    allowed = set(run_stages or UI_STEP_STAGES)
    ordered = [s for s in UI_STEP_STAGES if s in allowed]

    for stage in ordered:
        if _pending_for_stage(stage, min_score=min_score, progress_map=pmap or {}) > 0:
            return stage

    # PDF is not a UI step; show tailor while PDF conversions are pending.
    if "pdf" in allowed:
        if _pending_for_stage("pdf", min_score=min_score, progress_map=pmap or {}) > 0:
            return "tailor"

    if pmap:
        for stage in ordered:
            payload = (pmap.get(stage) or {}).get("payload") or {}
            if payload.get("waiting_upstream"):
                return stage

    return db_current_stage
