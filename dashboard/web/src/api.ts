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
  fit_score: number | null;
  score_reasoning: string | null;
  discovered_at: string | null;
  scored_at: string | null;
  detail_error: string | null;
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
  by_site: SiteCount[];
  score_distribution: ScoreDistributionItem[];
  score_buckets: ScoreBucket[];
  pipeline: Record<string, number>;
  extra?: Record<string, number>;
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

export async function fetchJobs(params: {
  min_score?: number;
  search?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}): Promise<{ jobs: Job[]; total: number }> {
  const q = new URLSearchParams();
  if (params.min_score != null) q.set("min_score", String(params.min_score));
  if (params.search) q.set("search", params.search);
  if (params.sort) q.set("sort", params.sort);
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  const res = await fetch(`${API}/jobs?${q}`);
  if (!res.ok) throw new Error("Failed to load jobs");
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

export async function startRun(body: {
  run_type?: string;
  stages?: string[] | null;
  stream?: boolean;
  dry_run?: boolean;
  min_score?: number;
  workers?: number;
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
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to start run");
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
