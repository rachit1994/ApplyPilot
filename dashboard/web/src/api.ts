export type Run = {
  id: string;
  run_type: string;
  status: string;
  stages: string[];
  stream: boolean;
  dry_run: boolean;
  current_stage: string | null;
  exit_code: number | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type RunEvent = {
  id?: number;
  run_id: string;
  event_type: string;
  stage?: string | null;
  level?: string;
  message?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};

export type Job = {
  url: string;
  title: string | null;
  site: string | null;
  location: string | null;
  remote?: string | null;
  salary: string | null;
  strategy?: string | null;
  fit_score: number | null;
  score_reasoning: string | null;
  score_role_key?: string | null;
  score_jd_fit?: number | null;
  pre_fit_score?: number | null;
  pre_filter_reason?: string | null;
  pre_filter_rejected_at?: string | null;
  discovered_at: string | null;
  scored_at: string | null;
  activity_at: string | null;
  detail_error: string | null;
  full_description?: string | null;
  detail_scraped_at?: string | null;
  application_url?: string | null;
  tailored_resume_path?: string | null;
  tailored_at?: string | null;
  tailor_attempts?: number | null;
  cover_letter_path?: string | null;
  cover_letter_at?: string | null;
  cover_attempts?: number | null;
  applied_at?: string | null;
  apply_status?: string | null;
  apply_error?: string | null;
  apply_attempts?: number | null;
  last_attempted_at?: string | null;
  verification_confidence?: string | null;
};

export type PipelineStageFilter = "all" | "tailored" | "ready" | "applied";

export type Application = {
  url: string;
  title: string | null;
  site: string | null;
  location: string | null;
  salary: string | null;
  fit_score: number | null;
  application_url: string | null;
  apply_status: string | null;
  apply_error: string | null;
  applied_at: string | null;
  last_attempted_at: string | null;
  apply_duration_ms: number | null;
  apply_attempts: number | null;
  apply_log_path: string | null;
  verification_confidence: string | null;
  tailored_resume_path?: string | null;
  form_filled?: ApplyFormFilled | null;
};

export type FormFieldSnapshot = {
  label: string;
  value: string;
  type?: string;
  empty?: boolean;
  source?: "snapshot" | "fill_action" | string;
};

export type ApplyFormFilled = {
  form_url?: string | null;
  page_title?: string | null;
  fields: FormFieldSnapshot[];
  fill_actions?: string[];
  visible_errors?: string[];
  empty_required?: unknown;
  field_count?: number;
  resume_pdf?: string | null;
  cover_pdf?: string | null;
  uploads?: Array<{
    label?: string;
    name?: string;
    required?: boolean;
    has_file?: boolean;
    file_name?: string;
  }>;
};

export type ApplyVerificationSummary = {
  decision: string;
  reasons: string[];
  status?: string;
  submit_click_ref?: string | null;
  submit_button_text?: string | null;
  pre_submit_url?: string | null;
  post_submit_url?: string | null;
  confirmation_copy?: string | null;
  screenshot_path?: string | null;
  verification_code_used?: string | null;
};

export type ApplyResultJson = {
  status?: string;
  reason?: string;
  submit_click_ref?: string;
  submit_button_text?: string;
  pre_submit_url?: string;
  post_submit_url?: string;
  confirmation_copy?: string;
  screenshot_path?: string;
  verification_code_used?: string;
};

export type ParsedApplyLog = {
  fields?: FormFieldSnapshot[];
  form_filled?: ApplyFormFilled | null;
  fill_actions?: string[];
  result_line?: string | null;
  result_json?: ApplyResultJson | null;
  verification?: ApplyVerificationSummary | null;
  form_url?: string | null;
  page_title?: string | null;
  visible_errors?: string[];
  empty_required?: unknown;
};

export type ApplicationLogDetail = {
  log_path?: string | null;
  log_excerpt?: string | null;
  parsed?: ParsedApplyLog | null;
};

export type ApplicationDetail = Application & {
  score_reasoning?: string | null;
  tailored_resume_path?: string | null;
  cover_letter_path?: string | null;
  log_detail?: ApplicationLogDetail | null;
};

export type PendingLogin = {
  domain: string;
  url?: string | null;
  reason?: string | null;
  has_google_signin?: boolean | null;
  since?: string | null;
};

export type LoginPendingResponse = {
  paused: boolean;
  pending: PendingLogin[];
};

export type LoginResumeResponse = {
  resumed_domain: string;
  requeued: number;
};

export type SiteCount = {
  site: string | null;
  count: number;
};

export type ScoreDistributionItem = {
  score: number;
  count: number;
};

export type ScoreBucket = {
  bucket: string;
  count: number;
};

export type LowScoreReason = {
  reason: string;
  count: number;
};

export type Stats = {
  total: number;
  scored: number;
  with_description: number;
  tailored: number;
  ready_to_apply: number;
  applied: number;
  priority_boards?: string[];
  apply_queue_order?: string;
  by_site: SiteCount[];
  score_distribution: ScoreDistributionItem[];
  score_buckets: ScoreBucket[];
  low_score_reasons?: LowScoreReason[];
  pipeline: Record<string, number>;
  triage_counts?: Record<string, number>;
  extra?: Record<string, number>;
};

export type SourceStats = {
  source: string;
  discovered: number;
  passed_filter: number;
  scored_ge7: number;
  tailored: number;
  efficiency: number;
};

export type OverviewRunBandStep = {
  id: string;
  label: string;
  done: number | null;
  pending: number | null;
  total: number | null;
  percent: number | null;
  detail: string | null;
  count_text?: string | null;
  state: "done" | "active" | "pending";
};

export type OverviewRunBand = {
  status: string;
  title: string;
  subtitle: string;
  run_id: string | null;
  run_type: string | null;
  current_stage: string | null;
  dry_run: boolean;
  steps: OverviewRunBandStep[];
  metrics: {
    throughput_per_min: number | null;
    score_pass_rate_percent?: number | null;
    run_cost_usd: number | null;
    error_count: number;
    eta_to_apply_text?: string | null;
    score_pass_rate_delta_text?: string | null;
    throughput_delta_text?: string | null;
    run_cost_delta_text?: string | null;
    error_rate_text?: string | null;
  };
};

export type OverviewKpis = {
  applied_30d: number;
  applied_30d_delta_text?: string | null;
  needs_verify: number;
  ready_to_apply: number;
  ready_to_apply_subtitle?: string | null;
  ready_to_apply_delta_text?: string | null;
  pipeline_total: number;
  pipeline_total_subtitle?: string | null;
  spend_today_usd: number;
  spend_cap_usd: number;
  spend_today_subtitle?: string | null;
  spend_today_delta_text?: string | null;
  callback_rate_14d: number | null;
  callback_rate_14d_delta_text?: string | null;
};

export type OverviewFunnelRow = {
  id: string;
  label: string;
  count: number;
  rate_percent: number | null;
};

export type OverviewScoreDistribution = {
  buckets: { score: number; count: number }[];
  mean: number | null;
  stdev: number | null;
  total_scored: number;
  apply_eligible_count: number;
};

export type OverviewOpportunity = {
  url: string;
  title: string | null;
  site: string | null;
  location: string | null;
  salary: string | null;
  fit_score: number | null;
  apply_status: string | null;
  activity_at: string | null;
};

export type OverviewSourceRow = {
  source: string;
  discovered: number;
  passed_filter: number;
  scored_ge7: number;
  tailored: number;
  efficiency: number;
};

export type DashboardActivityItem = {
  id: number;
  ts: string;
  level: string;
  stage: string | null;
  message: string;
  run_id: string | null;
  job_url: string | null;
  meta: Record<string, unknown>;
};

export type OverviewCaps = {
  spend_today_usd: number;
  spend_cap_usd: number;
  apply_today: number;
  apply_attempts_today?: number;
  apply_cap: number;
  tailor_today: number;
  tailor_cap: number;
  llm_provider_hint?: string | null;
  llm_spend_subtitle?: string | null;
  apply_subtitle?: string | null;
  tailor_subtitle?: string | null;
};

export type WorkerSnapshot = {
  worker_id: number;
  status: string | null;
  detail: string | null;
  progress_percent: number | null;
  updated_at: string | null;
};

export type OverviewFooter = {
  app_version: string;
  generated_at: string;
  build_ms: number;
  right_text?: string | null;
};

export type OverviewResponse = {
  runband: OverviewRunBand;
  kpis: OverviewKpis;
  funnel_subtitle?: string | null;
  funnel_meta?: string | null;
  funnel: OverviewFunnelRow[];
  score_distribution: OverviewScoreDistribution;
  score_distribution_subtitle?: string | null;
  score_distribution_meta?: string | null;
  top_opportunities: OverviewOpportunity[];
  top_opportunities_subtitle?: string | null;
  top_opportunities_chip_counts?: Record<string, number>;
  sources: OverviewSourceRow[];
  activity: DashboardActivityItem[];
  activity_subtitle?: string | null;
  caps: OverviewCaps;
  workers: WorkerSnapshot[];
  workers_subtitle?: string | null;
  footer: OverviewFooter;
};

export type HealthResponse = {
  status: string;
  app_dir?: string;
};

export type AgentSettings = {
  auto_apply_enabled: boolean;
  apply_min_score: number;
  tailor_per_job: boolean;
  cover_letter: boolean;
  cross_source_dedup: boolean;
};

export type AgentSettingsResponse = {
  agent: AgentSettings;
  updated_at: string | null;
};

const API = "/api";
const DASHBOARD_TOKEN_KEY = "applypilot_dashboard_token";

function dashboardAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(DASHBOARD_TOKEN_KEY)?.trim();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

function mergeHeaders(...parts: HeadersInit[]): HeadersInit {
  const headers = new Headers();
  for (const part of parts) {
    const h = new Headers(part);
    h.forEach((value, key) => headers.set(key, value));
  }
  return headers;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/health");
  if (!res.ok) throw new Error("Failed to load health");
  return res.json();
}

export async function fetchAgentSettings(): Promise<AgentSettingsResponse> {
  const res = await fetch(`${API}/settings/agent`, {
    headers: mergeHeaders(dashboardAuthHeaders()),
  });
  if (!res.ok) throw new Error("Failed to load agent settings");
  return res.json();
}

export async function patchAgentSettings(
  patch: Partial<AgentSettings>,
): Promise<AgentSettingsResponse> {
  const res = await fetch(`${API}/settings/agent`, {
    method: "PATCH",
    headers: mergeHeaders(
      { "Content-Type": "application/json" },
      dashboardAuthHeaders(),
    ),
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to save agent settings");
  }
  return res.json();
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${API}/stats`);
  if (!res.ok) throw new Error("Failed to load stats");
  const data = await res.json();
  return data.stats;
}

export async function fetchOverview(): Promise<OverviewResponse> {
  const res = await fetch(`${API}/overview`);
  if (!res.ok) throw new Error("Failed to load overview");
  return res.json();
}

export type LlmUsageBreakdownRow = {
  key: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_create_tokens: number;
  cost_usd: number;
};

export type LlmUsageDailyRow = {
  day: string;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  cache_read_tokens: number;
};

export type LlmUsageEventRow = {
  id: number;
  provider: string;
  model: string;
  operation: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_create_tokens: number;
  estimated: boolean;
  cost_usd: number;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type LlmUsageResponse = {
  month: string;
  generated_at: string;
  app_version: string;
  ledger_available: boolean;
  summary: {
    claude_today_usd: number;
    claude_month_usd: number;
    all_providers_today_usd: number;
    all_providers_month_usd: number;
    claude_calls_today: number;
    cache_read_tokens_today: number;
    cache_hit_rate_percent: number | null;
  };
  apply_config: {
    primary_model: string;
    fallback_model: string;
    prompt_slim: boolean;
    session_reuse: boolean;
    gmail_mcp: boolean;
  };
  by_model_month: LlmUsageBreakdownRow[];
  by_operation_month: LlmUsageBreakdownRow[];
  by_operation_today: LlmUsageBreakdownRow[];
  monthly_ledger: Array<{
    provider: string;
    model: string;
    operation: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_create_tokens: number;
    estimated_calls: number;
    cost_usd: number;
  }>;
  daily_claude: LlmUsageDailyRow[];
  recent_events: LlmUsageEventRow[];
  quota: { quota_blocked_jobs: number; quota_blocked_recent: number };
  providers_month: LlmUsageBreakdownRow[];
};

export async function fetchLlmUsage(month?: string): Promise<LlmUsageResponse> {
  const q = month ? `?month=${encodeURIComponent(month)}` : "";
  const res = await fetch(`${API}/llm-usage${q}`);
  if (!res.ok) throw new Error("Failed to load LLM usage");
  return res.json();
}

export async function fetchSourceStats(days = 7): Promise<SourceStats[]> {
  const res = await fetch(`${API}/source-stats?days=${encodeURIComponent(String(days))}`);
  if (!res.ok) throw new Error("Failed to load source stats");
  const data = await res.json();
  return data.sources ?? [];
}

export type TriageCounts = Record<string, number>;

export async function fetchTriageCounts(params: {
  min_score?: number;
  site?: string;
  search?: string;
  apply_status?: string;
  low_score_reason?: string;
}): Promise<TriageCounts> {
  const q = new URLSearchParams();
  if (params.min_score != null && params.min_score > 0) {
    q.set("min_score", String(params.min_score));
  }
  if (params.site) q.set("site", params.site);
  if (params.search) q.set("search", params.search);
  if (params.apply_status) q.set("apply_status", params.apply_status);
  if (params.low_score_reason) q.set("low_score_reason", params.low_score_reason);
  const res = await fetch(`${API}/jobs/triage-counts?${q}`);
  if (!res.ok) throw new Error("Failed to load triage counts");
  const data = await res.json();
  return data.counts ?? {};
}

export async function fetchJobs(params: {
  min_score?: number;
  site?: string;
  search?: string;
  pipeline_stage?: PipelineStageFilter;
  stage?: string;
  apply_status?: string;
  low_score_reason?: string;
  sort?: string;
  limit?: number;
  offset?: number;
  page?: number;
}): Promise<{
  jobs: Job[];
  total: number;
  limit?: number;
  offset?: number;
  page?: number;
  pages?: number;
}> {
  const q = new URLSearchParams();
  if (params.min_score != null && params.min_score > 0) {
    q.set("min_score", String(params.min_score));
  }
  if (params.site) q.set("site", params.site);
  if (params.search) q.set("search", params.search);
  if (params.stage) q.set("stage", params.stage);
  if (params.apply_status) q.set("apply_status", params.apply_status);
  if (params.low_score_reason) q.set("low_score_reason", params.low_score_reason);
  if (params.pipeline_stage && params.pipeline_stage !== "all") {
    q.set("pipeline_stage", params.pipeline_stage);
  }
  if (params.sort) q.set("sort", params.sort);
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (params.page != null && params.page > 0) q.set("page", String(params.page));
  if (!params.sort) q.set("sort", "activity_desc");
  const res = await fetch(`${API}/jobs?${q}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load jobs");
  return res.json();
}

export type ApplyErrorGroup = {
  apply_error: string;
  apply_status: string | null;
  count: number;
};

export async function fetchApplyErrorSummary(): Promise<{ groups: ApplyErrorGroup[] }> {
  const res = await fetch(`${API}/applications/errors`);
  if (!res.ok) throw new Error("Failed to load apply error summary");
  return res.json();
}

export async function fetchApplications(params: {
  limit?: number;
  offset?: number;
  include_failed?: boolean;
  status?: string;
  site?: string;
  search?: string;
  claude_escalated?: boolean;
  needs_attention?: boolean;
}): Promise<{ applications: Application[]; total: number }> {
  const q = new URLSearchParams();
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (params.include_failed) q.set("include_failed", "true");
  if (params.status) q.set("status", params.status);
  if (params.site) q.set("site", params.site);
  if (params.search) q.set("search", params.search);
  if (params.claude_escalated) q.set("claude_escalated", "true");
  if (params.needs_attention) q.set("needs_attention", "true");
  const res = await fetch(`${API}/applications?${q}`);
  if (!res.ok) throw new Error("Failed to load applications");
  return res.json();
}

export async function fetchAttentionApplications(params?: {
  limit?: number;
  offset?: number;
}): Promise<{ applications: Application[]; total: number }> {
  const q = new URLSearchParams();
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const res = await fetch(`${API}/applications/attention?${q}`);
  if (!res.ok) throw new Error("Failed to load attention applications");
  return res.json();
}

export type Referral = {
  url: string;
  title: string | null;
  company: string | null;
  site: string | null;
  location: string | null;
  fit_score: number | null;
  recruiter_name: string | null;
  recruiter_public_id: string | null;
  recruiter_scrape_error: string | null;
  referral_message: string | null;
  referral_status: string | null;
  referral_error: string | null;
  applied_at: string | null;
  referral_resume_path: string | null;
  can_scrape: boolean;
  can_template: boolean;
  can_connect: boolean;
  can_message: boolean;
};

export type ReferralsMeta = {
  outreach_enabled?: boolean;
  require_applied_before_send?: boolean;
  openoutreach?: { reachable: boolean; detail?: string | null };
};

export type ReferralAction = "scrape" | "draft" | "connect" | "message";

export async function fetchReferrals(params: {
  filter?: string;
  search?: string;
  min_score?: number;
  limit?: number;
  offset?: number;
}): Promise<{ referrals: Referral[]; total: number; meta: ReferralsMeta }> {
  const q = new URLSearchParams();
  if (params.filter) q.set("filter", params.filter);
  if (params.search) q.set("search", params.search);
  if (params.min_score != null) q.set("min_score", String(params.min_score));
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  const res = await fetch(`${API}/referrals?${q}`);
  if (!res.ok) throw new Error("Failed to load referrals");
  return res.json();
}

export async function postReferralAction(
  action: ReferralAction,
  urls: string[],
): Promise<{
  action: string;
  results: { url: string; ok: boolean; error?: string | null }[];
  summary: Record<string, unknown>;
}> {
  const res = await fetch(`${API}/referrals/actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, urls }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Referral action failed");
  }
  return res.json();
}

export async function fetchApplicationDetail(url: string): Promise<ApplicationDetail> {
  const q = new URLSearchParams({ url });
  const res = await fetch(`${API}/applications/detail?${q}`);
  if (!res.ok) throw new Error("Failed to load application detail");
  const data = await res.json();
  return data.application as ApplicationDetail;
}

export async function fetchConfirmApplication(
  url: string,
): Promise<{ ok: boolean; url: string }> {
  const q = new URLSearchParams({ url });
  const res = await fetch(`${API}/applications/confirm?${q}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Confirm application failed");
  }
  return res.json();
}

export async function fetchRetryApplication(url: string): Promise<{ ok: boolean; url: string }> {
  const q = new URLSearchParams({ url });
  const res = await fetch(`${API}/applications/retry?${q}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Retry application failed");
  }
  return res.json();
}

export async function fetchMarkApplicationApplied(
  url: string,
): Promise<{ ok: boolean; url: string }> {
  const q = new URLSearchParams({ url });
  const res = await fetch(`${API}/applications/mark-applied?${q}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Mark applied failed");
  }
  return res.json();
}

export async function fetchRequeueApplication(
  url: string,
): Promise<{ ok: boolean; url: string }> {
  const q = new URLSearchParams({ url });
  const res = await fetch(`${API}/applications/requeue?${q}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Requeue failed");
  }
  return res.json();
}

export async function fetchPendingLogins(): Promise<LoginPendingResponse> {
  const res = await fetch(`${API}/login/pending`);
  if (!res.ok) throw new Error("Failed to load pending logins");
  return res.json();
}

export async function postResumeLogin(domain?: string): Promise<LoginResumeResponse> {
  const res = await fetch(`${API}/login/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain: domain ?? null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Resume login failed");
  }
  return res.json();
}

export async function fetchRecentJobs(minutes = 60): Promise<Job[]> {
  const res = await fetch(`${API}/jobs/recent?minutes=${minutes}&limit=100`);
  if (!res.ok) throw new Error("Failed to load recent jobs");
  const data = await res.json();
  return data.jobs;
}

export async function fetchStages(): Promise<{
  order: string[];
  meta: Record<string, { desc: string }>;
}> {
  const res = await fetch(`${API}/meta/stages`);
  if (!res.ok) throw new Error("Failed to load stages");
  return res.json();
}

export async function fetchRuns(): Promise<Run[]> {
  const res = await fetch(`${API}/runs`);
  if (!res.ok) throw new Error("Failed to load runs");
  return res.json();
}

export async function fetchActiveRun(): Promise<Run | null> {
  const res = await fetch(`${API}/runs/active`);
  if (!res.ok) throw new Error("Failed to load active run");
  return res.json();
}

export async function fetchRun(runId: string): Promise<Run> {
  const res = await fetch(`${API}/runs/${runId}`);
  if (!res.ok) throw new Error("Failed to load run");
  return res.json();
}

/** REST backlog for completed runs; live updates use SSE via subscribeRunEvents. */
export async function fetchRunEventsHistory(
  runId: string,
  afterId = 0,
): Promise<RunEvent[]> {
  const res = await fetch(
    `${API}/runs/${runId}/events/history?after_id=${afterId}`,
  );
  if (!res.ok) throw new Error("Failed to load run events");
  return res.json();
}

export type InboxQueueItem = {
  conversation_urn: string;
  participant_public_id: string;
  fit_score: number;
  inbound_preview: string;
  extracted_title?: string | null;
  extracted_company?: string | null;
  reasoning?: string;
  eligible_to_send?: boolean;
  skip_reason?: string | null;
  rank?: number;
};

export async function fetchInboxQueue(limit = 50): Promise<{
  queue: InboxQueueItem[];
  total: number;
  stats: Record<string, number>;
}> {
  const res = await fetch(`${API}/inbox/queue?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load inbox queue");
  return res.json();
}

export type LearningStats = {
  nav_playbook: {
    total: number;
    by_status: Record<string, number>;
    by_source: Record<string, number>;
    by_ats_family: Record<string, number>;
  };
  cache_hit: {
    replay_count: number;
    llm_count: number;
    replay_pct: number;
  };
  field_strategy_total: number;
};

export type LearningReviewEvent = {
  id: number;
  ts?: string | null;
  job_url?: string | null;
  ats_family?: string | null;
  apex_host?: string | null;
  state_sig?: string | null;
  tier?: string | null;
  action_type?: string | null;
  outcome?: string | null;
  postcondition_met?: number | null;
};

export type LearningCluster = {
  state_sig: string;
  count: number;
  ats_family?: string | null;
  apex_host?: string | null;
  action_type?: string | null;
  tier?: string | null;
  outcome?: string | null;
};

export type LearningTierMix = {
  since_hours: number;
  tiers: Record<string, number>;
};

export type LearningEscalation = {
  ats_family: string;
  attempts: number;
  fail_fraction: number;
};

export type LearningEscalations = {
  since_hours: number;
  families: LearningEscalation[];
};

export type LearningInductionCandidate = {
  ats_family?: string | null;
  state_sig: string;
  action_type?: string | null;
  support: number;
};

export type LearningInduction = {
  min_support: number;
  candidates: LearningInductionCandidate[];
};

export async function fetchLearningStats(sinceHours = 24): Promise<LearningStats> {
  const res = await fetch(`${API}/learning/stats?since_hours=${sinceHours}`);
  if (!res.ok) throw new Error("Failed to load learning stats");
  return res.json();
}

export async function fetchLearningReview(limit = 50): Promise<{ events: LearningReviewEvent[] }> {
  const res = await fetch(`${API}/learning/review?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load learning review log");
  return res.json();
}

export async function fetchLearningClusters(limit = 20): Promise<{ clusters: LearningCluster[] }> {
  const res = await fetch(`${API}/learning/clusters?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load learning clusters");
  return res.json();
}

export async function fetchLearningTierMix(sinceHours = 24): Promise<LearningTierMix> {
  const res = await fetch(`${API}/learning/tier-mix?since_hours=${sinceHours}`);
  if (!res.ok) throw new Error("Failed to load learning tier mix");
  return res.json();
}

export async function fetchLearningEscalations(sinceHours = 24): Promise<LearningEscalations> {
  const res = await fetch(`${API}/learning/escalations?since_hours=${sinceHours}`);
  if (!res.ok) throw new Error("Failed to load learning escalations");
  return res.json();
}

export async function fetchLearningInduction(minSupport = 3): Promise<LearningInduction> {
  const res = await fetch(`${API}/learning/induction?min_support=${minSupport}`);
  if (!res.ok) throw new Error("Failed to load induction candidates");
  return res.json();
}

export async function postLearningPromote(
  stateSig: string,
  scope = "host",
): Promise<{ ok: boolean; state_sig: string; scope: string; status: string }> {
  const res = await fetch(`${API}/learning/promote`, {
    method: "POST",
    headers: mergeHeaders(
      { "Content-Type": "application/json" },
      dashboardAuthHeaders(),
    ),
    body: JSON.stringify({ state_sig: stateSig, scope }),
  });
  if (!res.ok) throw new Error("Failed to promote playbook entry");
  return res.json();
}

export async function postLearningBan(
  stateSig: string,
  scope = "host",
): Promise<{ ok: boolean; state_sig: string; scope: string; status: string }> {
  const res = await fetch(`${API}/learning/ban`, {
    method: "POST",
    headers: mergeHeaders(
      { "Content-Type": "application/json" },
      dashboardAuthHeaders(),
    ),
    body: JSON.stringify({ state_sig: stateSig, scope }),
  });
  if (!res.ok) throw new Error("Failed to ban playbook entry");
  return res.json();
}

export async function postInboxScan(limit?: number): Promise<Record<string, unknown>> {
  const q = limit != null ? `?limit=${limit}` : "";
  const res = await fetch(`${API}/inbox/scan${q}`, {
    method: "POST",
    headers: dashboardAuthHeaders(),
  });
  if (!res.ok) throw new Error("Inbox scan failed");
  return res.json();
}

export async function postInboxRun(opts: {
  action?: string;
  limit?: number;
  dry_run?: boolean;
  subprocess?: boolean;
}): Promise<Record<string, unknown>> {
  const q = new URLSearchParams();
  if (opts.action) q.set("action", opts.action);
  if (opts.limit != null) q.set("limit", String(opts.limit));
  if (opts.dry_run) q.set("dry_run", "true");
  if (opts.subprocess === false) q.set("subprocess", "false");
  const res = await fetch(`${API}/inbox/run?${q}`, {
    method: "POST",
    headers: dashboardAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Inbox run failed");
  }
  return res.json();
}

export type FieldOverrideRow = {
  label: string;
  value: string;
  updated_at?: string | null;
};

export async function fetchFieldOverrides(): Promise<{ overrides: FieldOverrideRow[] }> {
  const res = await fetch(`${API}/field-overrides`);
  if (!res.ok) throw new Error("Failed to load field overrides");
  return res.json();
}

export async function setFieldOverride(label: string, value: string): Promise<void> {
  const q = new URLSearchParams({ label, value });
  const res = await fetch(`${API}/field-overrides?${q}`, {
    method: "POST",
    headers: dashboardAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to save field override");
}

export async function deleteFieldOverride(label: string): Promise<void> {
  const q = new URLSearchParams({ label });
  const res = await fetch(`${API}/field-overrides?${q}`, {
    method: "DELETE",
    headers: dashboardAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete field override");
}

export async function bulkStageApplications(body: {
  urls: string[];
  action: "stage" | "unstage" | "dismiss";
}): Promise<{ updated: number; skipped: string[]; action: string }> {
  const res = await fetch(`${API}/applications/bulk-stage`, {
    method: "POST",
    headers: mergeHeaders(
      { "Content-Type": "application/json" },
      dashboardAuthHeaders(),
    ),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Bulk stage failed");
  }
  return res.json();
}

export async function startRun(body: {
  run_type?: string;
  stages?: string[] | null;
  stream?: boolean;
  dry_run?: boolean;
  min_score?: number;
  workers?: number;
  limit?: number;
  watch?: boolean;
  pace?: boolean;
  headless?: boolean;
  continuous?: boolean;
  prepare?: boolean;
  staged_only?: boolean;
  inbox_action?: string;
}): Promise<Run> {
  const res = await fetch(`${API}/runs`, {
    method: "POST",
    headers: mergeHeaders(
      { "Content-Type": "application/json" },
      dashboardAuthHeaders(),
    ),
    body: JSON.stringify({
      run_type: body.run_type ?? "pipeline",
      stages: body.stages ?? null,
      stream: body.stream ?? false,
      dry_run: body.dry_run ?? false,
      min_score: body.min_score ?? 7,
      workers: body.workers ?? 1,
      limit: body.limit,
      watch: body.watch,
      pace: body.pace,
      headless: body.headless,
      continuous: body.continuous,
      prepare: body.prepare,
      staged_only: body.staged_only,
      inbox_action: body.inbox_action,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = "Failed to start run";
    try {
      const err = JSON.parse(text) as { detail?: string | { msg?: string }[] };
      if (typeof err.detail === "string") {
        detail = err.detail;
      } else if (Array.isArray(err.detail)) {
        detail = err.detail.map((d) => d.msg ?? String(d)).join("; ");
      }
    } catch {
      if (text.trim()) {
        detail = text.trim().slice(0, 300);
      }
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function stopRun(runId: string): Promise<Run> {
  const res = await fetch(`${API}/runs/${runId}/stop`, {
    method: "POST",
    headers: dashboardAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to stop run");
  return res.json();
}

export function subscribeRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  initialAfterId = 0,
): () => void {
  let closed = false;
  let afterId = initialAfterId;
  let backoffMs = 1000;
  let source: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (closed) return;
    source?.close();
    source = new EventSource(`${API}/runs/${runId}/events?after_id=${afterId}`);

    source.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as RunEvent;
        if (event.id != null) {
          afterId = Math.max(afterId, event.id);
        }
        onEvent(event);
        backoffMs = 1000;
      } catch {
        /* ignore parse errors */
      }
    };

    source.onerror = () => {
      source?.close();
      source = null;
      if (closed) return;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 30_000);
    };
  };

  connect();

  return () => {
    closed = true;
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    source?.close();
    source = null;
  };
}
