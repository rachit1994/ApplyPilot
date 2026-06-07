import type { DashboardActivityItem, RunEvent } from "../api";
import { effectiveLogLevel } from "./logLevel";

export type DevlogRow = {
  id: string | number;
  ts: string;
  stage: string;
  message: string;
  level: string;
  jobUrl: string | null;
};

const PIPELINE_STAGES = new Set([
  "discover",
  "enrich",
  "score",
  "tailor",
  "cover",
  "pdf",
  "apply",
  "refer",
  "role_resumes",
]);

const URL_SUFFIX_RE = / \| (https?:\/\/\S+)\s*$/;
const URL_COLON_RE = /\bURL:\s*(https?:\/\/\S+)/i;

function stripTrailingPunctuation(url: string): string {
  return url.replace(/[.,;)]+$/, "");
}

export function extractJobUrlFromMessage(message: string | undefined): string | null {
  if (!message) return null;
  const text = message.trim();
  const suffix = URL_SUFFIX_RE.exec(text);
  if (suffix?.[1]) return stripTrailingPunctuation(suffix[1]);
  const colon = URL_COLON_RE.exec(text);
  if (colon?.[1]) return stripTrailingPunctuation(colon[1]);
  return null;
}

export function extractJobUrl(
  message: string | undefined,
  payload?: Record<string, unknown> | null,
  jobUrl?: string | null,
): string | null {
  const direct = (jobUrl ?? "").trim();
  if (direct) return direct;
  const fromPayload = payload?.job_url;
  if (typeof fromPayload === "string" && fromPayload.trim()) {
    return fromPayload.trim();
  }
  return extractJobUrlFromMessage(message);
}

export function formatDevlogLocalTime(ts: string | undefined): string {
  if (!ts) return "—";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) {
    const tIdx = ts.indexOf("T");
    if (tIdx === -1) return ts.slice(11, 19) || "—";
    return ts.slice(tIdx + 1, tIdx + 9);
  }
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function normalizeStageLabel(stage: string | null | undefined): string {
  const value = (stage ?? "").trim().toLowerCase();
  if (!value) return "—";
  if (PIPELINE_STAGES.has(value)) return value;
  if (value === "run_started" || value === "run_finished") return "run";
  return value;
}

function resolveStage(event: RunEvent, currentStage: string | null): string {
  if (event.stage?.trim()) return normalizeStageLabel(event.stage);
  if (event.event_type === "stage_start" || event.event_type === "stage_end" || event.event_type === "stage_error") {
    return normalizeStageLabel(event.stage ?? currentStage);
  }
  if (event.event_type === "run_started" || event.event_type === "run_finished") {
    return "run";
  }
  if (currentStage) return normalizeStageLabel(currentStage);
  return "—";
}

export function buildDevlogRowsFromRunEvents(events: RunEvent[]): DevlogRow[] {
  const rows: DevlogRow[] = [];
  let currentStage: string | null = null;

  for (const event of events) {
    if (
      event.event_type !== "log" &&
      event.event_type !== "stage_error" &&
      event.event_type !== "run_started" &&
      event.event_type !== "run_finished" &&
      event.event_type !== "stage_start" &&
      event.event_type !== "stage_end"
    ) {
      continue;
    }

    if (event.event_type === "stage_start" || event.event_type === "stage_end" || event.event_type === "stage_error") {
      if (event.stage?.trim()) currentStage = event.stage.trim();
    } else if (event.stage?.trim()) {
      currentStage = event.stage.trim();
    }

    const message = event.message?.trim();
    if (!message) continue;

    rows.push({
      id: event.id ?? `${event.created_at ?? ""}-${event.event_type}-${message.slice(0, 40)}`,
      ts: event.created_at ?? "",
      stage: resolveStage(event, currentStage),
      message,
      level: effectiveLogLevel(event),
      jobUrl: extractJobUrl(message, event.payload),
    });
  }

  return rows;
}

export function devlogRowFromActivity(ev: DashboardActivityItem): DevlogRow {
  return {
    id: ev.id,
    ts: ev.ts,
    stage: normalizeStageLabel(ev.stage),
    message: ev.message ?? "—",
    level: ev.level ?? "info",
    jobUrl: extractJobUrl(ev.message, ev.meta, ev.job_url),
  };
}
