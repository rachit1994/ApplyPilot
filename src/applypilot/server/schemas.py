"""Pydantic models for the dashboard API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StartRunRequest(BaseModel):
    run_type: str = "pipeline"
    stages: list[str] | None = None
    stream: bool = False
    dry_run: bool = False
    min_score: int = 7
    workers: int = 1
    validation_mode: str = "normal"
    force: bool = False


class RunResponse(BaseModel):
    id: str
    run_type: str
    status: str
    stages: list[str] = Field(default_factory=list)
    stream: bool = False
    dry_run: bool = False
    current_stage: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    event_count: int = 0
    last_event_message: str | None = None


class JobRow(BaseModel):
    url: str
    title: str | None = None
    site: str | None = None
    location: str | None = None
    salary: str | None = None
    fit_score: int | None = None
    score_reasoning: str | None = None
    discovered_at: str | None = None
    scored_at: str | None = None
    detail_error: str | None = None


class JobsResponse(BaseModel):
    jobs: list[JobRow]
    total: int


class SiteCount(BaseModel):
    site: str | None
    count: int


class ScoreDistributionItem(BaseModel):
    score: int
    count: int


class ScoreBucket(BaseModel):
    bucket: str
    count: int


class StatsPayload(BaseModel):
    """Dashboard stats snapshot from get_stats()."""

    total: int = 0
    scored: int = 0
    with_description: int = 0
    tailored: int = 0
    ready_to_apply: int = 0
    applied: int = 0
    by_site: list[SiteCount] = Field(default_factory=list)
    score_distribution: list[ScoreDistributionItem] = Field(default_factory=list)
    score_buckets: list[ScoreBucket] = Field(default_factory=list)
    pipeline: dict[str, int] = Field(default_factory=dict)
    # Additional scalar fields from get_stats() not in pipeline
    extra: dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    stats: StatsPayload
