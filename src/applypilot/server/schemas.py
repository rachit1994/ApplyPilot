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
    prepare: bool = False
    staged_only: bool = False
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
    remote: str | None = None
    salary: str | None = None
    strategy: str | None = None
    fit_score: int | None = None
    score_reasoning: str | None = None
    score_role_key: str | None = None
    score_jd_fit: int | None = None
    pre_fit_score: int | None = None
    pre_filter_reason: str | None = None
    pre_filter_rejected_at: str | None = None
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


class BulkStageRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    action: str = Field(description="stage | unstage | dismiss")


class JobsResponse(BaseModel):
    jobs: list[JobRow]
    total: int
    limit: int = 100
    offset: int = 0
    page: int = 1
    pages: int = 0


class TriageCountsResponse(BaseModel):
    """Jobs tab chip counts; respects the same query filters as GET /api/jobs."""

    counts: dict[str, int] = Field(default_factory=dict)


class SiteCount(BaseModel):
    site: str | None
    count: int


class ScoreDistributionItem(BaseModel):
    score: int
    count: int


class ScoreBucket(BaseModel):
    bucket: str
    count: int


class LowScoreReason(BaseModel):
    reason: str
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
    low_score_reasons: list[LowScoreReason] = Field(default_factory=list)
    pipeline: dict[str, int] = Field(default_factory=dict)
    triage_counts: dict[str, int] = Field(default_factory=dict)
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


# --- Home overview (GET /api/overview) ---------------------------------


class OverviewRunBandStep(BaseModel):
    """One pipeline stepper segment for the Mission Control run band."""

    id: str
    label: str
    done: int | None = None
    pending: int | None = None
    total: int | None = None
    percent: int | None = None
    detail: str | None = None
    count_text: str | None = None
    state: str = "pending"  # done | active | pending


class OverviewRunBandMetrics(BaseModel):
    throughput_per_min: float | None = None
    score_pass_rate_percent: float | None = None
    run_cost_usd: float | None = None
    error_count: int = 0
    eta_to_apply_text: str | None = None
    score_pass_rate_delta_text: str | None = None
    throughput_delta_text: str | None = None
    run_cost_delta_text: str | None = None
    error_rate_text: str | None = None


class OverviewRunBand(BaseModel):
    status: str
    title: str
    subtitle: str
    run_id: str | None = None
    run_type: str | None = None
    current_stage: str | None = None
    dry_run: bool = False
    steps: list[OverviewRunBandStep] = Field(default_factory=list)
    metrics: OverviewRunBandMetrics = Field(default_factory=OverviewRunBandMetrics)


class OverviewKpis(BaseModel):
    applied_30d: int = 0
    applied_30d_delta_text: str | None = None
    needs_verify: int = 0
    ready_to_apply: int = 0
    ready_to_apply_subtitle: str | None = None
    ready_to_apply_delta_text: str | None = None
    pipeline_total: int = 0
    pipeline_total_subtitle: str | None = None
    spend_today_usd: float = 0.0
    spend_cap_usd: float = 50.0
    spend_today_subtitle: str | None = None
    spend_today_delta_text: str | None = None
    callback_rate_14d: float | None = None
    callback_rate_14d_delta_text: str | None = None


class OverviewFunnelRow(BaseModel):
    id: str
    label: str
    count: int = 0
    rate_percent: float | None = None


class OverviewScoreDistribution(BaseModel):
    buckets: list[ScoreDistributionItem] = Field(default_factory=list)
    mean: float | None = None
    stdev: float | None = None
    total_scored: int = 0
    apply_eligible_count: int = 0


class OverviewOpportunityRow(BaseModel):
    url: str
    title: str | None = None
    site: str | None = None
    location: str | None = None
    salary: str | None = None
    fit_score: int | None = None
    apply_status: str | None = None
    activity_at: str | None = None


class OverviewSourceRow(BaseModel):
    source: str
    discovered: int = 0
    passed_filter: int = 0
    scored_ge7: int = 0
    tailored: int = 0
    efficiency: float = 0.0


class DashboardActivityItem(BaseModel):
    id: int
    ts: str
    level: str
    stage: str | None = None
    message: str
    run_id: str | None = None
    job_url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class DashboardActivityListResponse(BaseModel):
    events: list[DashboardActivityItem] = Field(default_factory=list)


class OverviewCaps(BaseModel):
    spend_today_usd: float = 0.0
    spend_cap_usd: float = 50.0
    apply_today: int = 0
    apply_attempts_today: int = 0
    apply_cap: int = 60
    tailor_today: int = 0
    tailor_cap: int = 80
    llm_provider_hint: str | None = None
    llm_spend_subtitle: str | None = None
    apply_subtitle: str | None = None
    tailor_subtitle: str | None = None


class OverviewWorkerSnapshot(BaseModel):
    worker_id: int
    status: str | None = None
    detail: str | None = None
    progress_percent: int | None = None
    updated_at: str | None = None


class OverviewFooter(BaseModel):
    app_version: str
    generated_at: str
    build_ms: float = 0.0
    right_text: str | None = None


class OverviewResponse(BaseModel):
    runband: OverviewRunBand
    kpis: OverviewKpis
    funnel_subtitle: str | None = None
    funnel_meta: str | None = None
    funnel: list[OverviewFunnelRow] = Field(default_factory=list)
    score_distribution: OverviewScoreDistribution = Field(
        default_factory=OverviewScoreDistribution
    )
    score_distribution_subtitle: str | None = None
    score_distribution_meta: str | None = None
    top_opportunities: list[OverviewOpportunityRow] = Field(default_factory=list)
    top_opportunities_subtitle: str | None = None
    top_opportunities_chip_counts: dict[str, int] = Field(default_factory=dict)
    sources: list[OverviewSourceRow] = Field(default_factory=list)
    activity: list[DashboardActivityItem] = Field(default_factory=list)
    activity_subtitle: str | None = None
    caps: OverviewCaps = Field(default_factory=OverviewCaps)
    workers: list[OverviewWorkerSnapshot] = Field(default_factory=list)
    workers_subtitle: str | None = None
    footer: OverviewFooter


class WorkersResponse(BaseModel):
    workers: list[OverviewWorkerSnapshot] = Field(default_factory=list)
    run_id: str | None = None


# --- LLM / Claude usage (GET /api/llm-usage) ---------------------------


class LlmUsageBreakdownRow(BaseModel):
    key: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    cost_usd: float = 0.0


class LlmUsageDailyRow(BaseModel):
    day: str
    calls: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    cache_read_tokens: int = 0


class LlmUsageEventRow(BaseModel):
    id: int
    provider: str
    model: str
    operation: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    estimated: bool = False
    cost_usd: float = 0.0
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LlmUsageMonthlyLedgerRow(BaseModel):
    provider: str
    model: str
    operation: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    estimated_calls: int = 0
    cost_usd: float = 0.0


class LlmUsageSummary(BaseModel):
    claude_today_usd: float = 0.0
    claude_month_usd: float = 0.0
    all_providers_today_usd: float = 0.0
    all_providers_month_usd: float = 0.0
    claude_calls_today: int = 0
    cache_read_tokens_today: int = 0
    cache_hit_rate_percent: float | None = None


class LlmUsageApplyConfig(BaseModel):
    primary_model: str = "haiku"
    fallback_model: str = "sonnet"
    prompt_slim: bool = True
    session_reuse: bool = True
    gmail_mcp: bool = False


class LlmUsageQuotaStats(BaseModel):
    quota_blocked_jobs: int = 0
    quota_blocked_recent: int = 0


class AgentSettingsPayload(BaseModel):
    auto_apply_enabled: bool = True
    apply_min_score: float = 7.0
    tailor_per_job: bool = True
    cover_letter: bool = True
    cross_source_dedup: bool = True


class AgentSettingsResponse(BaseModel):
    agent: AgentSettingsPayload
    updated_at: str | None = None


class AgentSettingsPatch(BaseModel):
    auto_apply_enabled: bool | None = None
    apply_min_score: float | None = Field(default=None, ge=0, le=10)
    tailor_per_job: bool | None = None
    cover_letter: bool | None = None
    cross_source_dedup: bool | None = None


class LlmUsageResponse(BaseModel):
    month: str
    generated_at: str
    app_version: str
    ledger_available: bool = False
    summary: LlmUsageSummary = Field(default_factory=LlmUsageSummary)
    apply_config: LlmUsageApplyConfig = Field(default_factory=LlmUsageApplyConfig)
    by_model_month: list[LlmUsageBreakdownRow] = Field(default_factory=list)
    by_operation_month: list[LlmUsageBreakdownRow] = Field(default_factory=list)
    by_operation_today: list[LlmUsageBreakdownRow] = Field(default_factory=list)
    monthly_ledger: list[LlmUsageMonthlyLedgerRow] = Field(default_factory=list)
    daily_claude: list[LlmUsageDailyRow] = Field(default_factory=list)
    recent_events: list[LlmUsageEventRow] = Field(default_factory=list)
    quota: LlmUsageQuotaStats = Field(default_factory=LlmUsageQuotaStats)
    providers_month: list[LlmUsageBreakdownRow] = Field(default_factory=list)
