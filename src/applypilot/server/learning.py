"""Self-learning apply API — playbook stats, review log, owner promote/ban."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from applypilot.apply.direct import playbook
from applypilot.apply.direct.playbook_seed import playbook_stats
from applypilot.apply.direct.review_log import cache_hit_rate, dedupe_clusters, list_recent
from applypilot.database import get_connection, init_db

router = APIRouter(prefix="/learning", tags=["learning"])


class PlaybookActionRequest(BaseModel):
    state_sig: str
    scope: str = "host"


class LearningStatsResponse(BaseModel):
    nav_playbook: dict
    cache_hit: dict
    field_strategy_total: int


class ReviewEventRow(BaseModel):
    id: int
    ts: str | None = None
    job_url: str | None = None
    ats_family: str | None = None
    apex_host: str | None = None
    state_sig: str | None = None
    tier: str | None = None
    action_type: str | None = None
    outcome: str | None = None
    postcondition_met: int | None = None


class ReviewLogResponse(BaseModel):
    events: list[ReviewEventRow]


class ClusterRow(BaseModel):
    state_sig: str
    count: int
    ats_family: str | None = None
    apex_host: str | None = None
    action_type: str | None = None
    tier: str | None = None
    outcome: str | None = None


class ClustersResponse(BaseModel):
    clusters: list[ClusterRow]


class PlaybookActionResponse(BaseModel):
    ok: bool = True
    state_sig: str
    scope: str
    status: str


def _field_strategy_total(conn) -> int:
    playbook.ensure_playbook_tables(conn)
    row = conn.execute("SELECT COUNT(*) AS n FROM field_strategy").fetchone()
    return int(row["n"] if row else 0)


@router.get("/stats", response_model=LearningStatsResponse)
def api_learning_stats(since_hours: int = 24) -> LearningStatsResponse:
    init_db()
    conn = get_connection()
    return LearningStatsResponse(
        nav_playbook=playbook_stats(conn),
        cache_hit=cache_hit_rate(conn, since_hours=max(1, min(since_hours, 168))),
        field_strategy_total=_field_strategy_total(conn),
    )


@router.get("/review", response_model=ReviewLogResponse)
def api_learning_review(limit: int = 50) -> ReviewLogResponse:
    init_db()
    conn = get_connection()
    rows = list_recent(conn, limit=max(1, min(limit, 200)))
    return ReviewLogResponse(events=[ReviewEventRow.model_validate(r) for r in rows])


@router.get("/clusters", response_model=ClustersResponse)
def api_learning_clusters(limit: int = 20) -> ClustersResponse:
    init_db()
    conn = get_connection()
    rows = dedupe_clusters(conn, limit=max(1, min(limit, 100)))
    return ClustersResponse(clusters=[ClusterRow.model_validate(r) for r in rows])


@router.post("/promote", response_model=PlaybookActionResponse)
def api_learning_promote(body: PlaybookActionRequest) -> PlaybookActionResponse:
    init_db()
    entry = playbook.promote(body.state_sig, scope=body.scope, status="trusted")
    if entry is None:
        raise HTTPException(status_code=404, detail="nav_playbook entry not found")
    return PlaybookActionResponse(
        state_sig=body.state_sig,
        scope=body.scope,
        status=entry.status,
    )


@router.post("/ban", response_model=PlaybookActionResponse)
def api_learning_ban(body: PlaybookActionRequest) -> PlaybookActionResponse:
    init_db()
    entry = playbook.promote(body.state_sig, scope=body.scope, status="banned")
    if entry is None:
        raise HTTPException(status_code=404, detail="nav_playbook entry not found")
    return PlaybookActionResponse(
        state_sig=body.state_sig,
        scope=body.scope,
        status=entry.status,
    )
