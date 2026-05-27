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
  salary: string | null;
  strategy?: string | null;
  fit_score: number | null;
  score_reasoning: string | null;
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
  pipeline: Record<string, number>;
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

export type HealthResponse = {
  status: string;
  app_dir?: string;
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

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${API}/stats`);
  if (!res.ok) throw new Error("Failed to load stats");
  const data = await res.json();
  return data.stats;
}

export async function fetchSourceStats(days = 7): Promise<SourceStats[]> {
  const res = await fetch(`${API}/source-stats?days=${encodeURIComponent(String(days))}`);
  if (!res.ok) throw new Error("Failed to load source stats");
  const data = await res.json();
  return data.sources ?? [];
}

export async function fetchJobs(params: {
  min_score?: number;
  site?: string;
  search?: string;
  pipeline_stage?: PipelineStageFilter;
  stage?: string;
  apply_status?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}): Promise<{ jobs: Job[]; total: number }> {
  const q = new URLSearchParams();
  if (params.min_score != null && params.min_score > 0) {
    q.set("min_score", String(params.min_score));
  }
  if (params.site) q.set("site", params.site);
  if (params.search) q.set("search", params.search);
  if (params.stage) q.set("stage", params.stage);
  if (params.apply_status) q.set("apply_status", params.apply_status);
  if (params.pipeline_stage && params.pipeline_stage !== "all") {
    q.set("pipeline_stage", params.pipeline_stage);
  }
  if (params.sort) q.set("sort", params.sort);
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (!params.sort) q.set("sort", "activity_desc");
  const res = await fetch(`${API}/jobs?${q}`);
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
}): Promise<{ applications: Application[]; total: number }> {
  const q = new URLSearchParams();
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (params.include_failed) q.set("include_failed", "true");
  if (params.status) q.set("status", params.status);
  if (params.site) q.set("site", params.site);
  if (params.search) q.set("search", params.search);
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
