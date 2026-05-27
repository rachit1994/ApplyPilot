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
    limit: int | None = None
    watch: bool = False
    pace: bool = False
    headless: bool = False
    continuous: bool = False
    inbox_action: str = "pipeline"


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
    strategy: str | None = None
    fit_score: int | None = None
    score_reasoning: str | None = None
    discovered_at: str | None = None
    scored_at: str | None = None
    activity_at: str | None = None
    detail_error: str | None = None
    full_description: str | None = None
    detail_scraped_at: str | None = None
    application_url: str | None = None
    tailored_resume_path: str | None = None
    tailored_at: str | None = None
    tailor_attempts: int | None = None
    cover_letter_path: str | None = None
    cover_letter_at: str | None = None
    cover_attempts: int | None = None
    applied_at: str | None = None
    apply_status: str | None = None
    apply_error: str | None = None
    apply_attempts: int | None = None
    last_attempted_at: str | None = None
    verification_confidence: str | None = None


class ApplicationRow(BaseModel):
    url: str
    title: str | None = None
    site: str | None = None
    location: str | None = None
    salary: str | None = None
    fit_score: int | None = None
    application_url: str | None = None
    apply_status: str | None = None
    apply_error: str | None = None
    applied_at: str | None = None
    last_attempted_at: str | None = None
    apply_duration_ms: int | None = None
    apply_attempts: int | None = None
    apply_log_path: str | None = None
    verification_confidence: str | None = None


class ApplicationsResponse(BaseModel):
    applications: list[ApplicationRow]
    total: int


class AttentionApplicationsResponse(BaseModel):
    applications: list[ApplicationRow]
    total: int


class ApplyErrorSummaryRow(BaseModel):
    apply_error: str
    apply_status: str | None = None
    count: int


class ApplyErrorSummaryResponse(BaseModel):
    groups: list[ApplyErrorSummaryRow]


class ApplicationDetailResponse(BaseModel):
    application: dict[str, Any]


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
    priority_boards: list[str] = Field(default_factory=list)
    apply_queue_order: str = ""
    by_site: list[SiteCount] = Field(default_factory=list)
    score_distribution: list[ScoreDistributionItem] = Field(default_factory=list)
    score_buckets: list[ScoreBucket] = Field(default_factory=list)
    pipeline: dict[str, int] = Field(default_factory=dict)
    # Additional scalar fields from get_stats() not in pipeline
    extra: dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    stats: StatsPayload


class SourceStatsRow(BaseModel):
    source: str
    discovered: int = 0
    passed_filter: int = 0
    scored_ge7: int = 0
    tailored: int = 0
    efficiency: float = 0.0


class SourceStatsResponse(BaseModel):
    sources: list[SourceStatsRow] = Field(default_factory=list)


class ReferralRow(BaseModel):
    url: str
    title: str | None = None
    company: str | None = None
    site: str | None = None
    location: str | None = None
    fit_score: int | None = None
    recruiter_name: str | None = None
    recruiter_public_id: str | None = None
    recruiter_scrape_error: str | None = None
    referral_message: str | None = None
    referral_status: str | None = None
    referral_error: str | None = None
    applied_at: str | None = None
    referral_resume_path: str | None = None
    can_scrape: bool = False
    can_template: bool = False
    can_connect: bool = False
    can_message: bool = False


class ReferralsResponse(BaseModel):
    referrals: list[ReferralRow]
    total: int
    meta: dict[str, Any] = Field(default_factory=dict)


class ReferralActionRequest(BaseModel):
    action: str
    urls: list[str] = Field(default_factory=list)


class ReferralActionResult(BaseModel):
    url: str
    ok: bool
    error: str | None = None


class ReferralActionResponse(BaseModel):
    action: str
    results: list[ReferralActionResult]
    summary: dict[str, Any] = Field(default_factory=dict)
