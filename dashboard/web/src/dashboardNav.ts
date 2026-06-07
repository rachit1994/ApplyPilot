import type { Job, Stats } from "./api";
import { jobPipelineStage } from "./utils/jobPipeline";

/** Run pipeline stages (CLI / API), not dashboard pages. */
export const PIPELINE_STAGE_IDS = [
  "discover",
  "enrich",
  "filter",
  "score",
  "tailor",
  "cover",
  "pdf",
] as const;

export type PipelineStageId = (typeof PIPELINE_STAGE_IDS)[number];

export type DashboardPage =
  | "home"
  | "jobs"
  | "apply"
  | "applications"
  | "outreach"
  | "pipeline"
  | "learning"
  | "settings";

export const STAGE_LABELS: Record<PipelineStageId, string> = {
  discover: "Discover",
  enrich: "Enrich",
  filter: "Filter",
  score: "Score",
  tailor: "Tailor",
  cover: "Cover",
  pdf: "PDF",
};

export const STAGE_DESCRIPTIONS: Record<PipelineStageId, string> = {
  discover: "Job discovery — JobSpy, Workday, feeds, and smart extract.",
  enrich: "Pull full descriptions and application URLs for new jobs.",
  filter: "Reject low-fit jobs before LLM review.",
  score: "LLM fit scoring against your profile.",
  tailor: "Tailor resumes per job.",
  cover: "Generate cover letters for scored roles.",
  pdf: "Convert tailored resumes and letters to PDF.",
};

export function isPipelineStageId(value: string): value is PipelineStageId {
  return (PIPELINE_STAGE_IDS as readonly string[]).includes(value);
}

export function isDashboardPage(value: string): value is DashboardPage {
  return (
    value === "home" ||
    value === "jobs" ||
    value === "apply" ||
    value === "applications" ||
    value === "outreach" ||
    value === "pipeline" ||
    value === "learning" ||
    value === "settings"
  );
}

const STAGE_JOB_LABELS: Record<PipelineStageId, string[]> = {
  discover: ["Discovered"],
  enrich: ["Enriched", "Enrich error"],
  filter: ["Rejected"],
  score: ["Scored", "Tailor exhausted"],
  tailor: ["Tailored", "Cover"],
  cover: ["Cover"],
  pdf: ["Tailored", "Cover", "Ready"],
};

export function jobMatchesStage(job: Job, stage: PipelineStageId): boolean {
  const label = jobPipelineStage(job);
  return STAGE_JOB_LABELS[stage].includes(label);
}

export function filterEventsForStage<T extends { stage?: string | null; event_type?: string }>(
  events: T[],
  stage: PipelineStageId,
): T[] {
  return events.filter((e) => {
    if (e.stage === stage) return true;
    if (e.event_type === "run_started" || e.event_type === "run_finished") return true;
    if (e.event_type === "stats_tick") return true;
    return false;
  });
}

export function pageGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning, Rachit.";
  if (hour < 17) return "Good afternoon, Rachit.";
  return "Good evening, Rachit.";
}

export function pageTitle(page: DashboardPage): string {
  if (page === "apply") return "Apply";
  if (page === "applications") return "Applications";
  if (page === "jobs") return "Jobs";
  if (page === "outreach") return "Outreach";
  if (page === "pipeline") return "Pipeline";
  if (page === "learning") return "Learning";
  if (page === "settings") return "Settings";
  return "Today";
}

export function pageSubtitle(page: DashboardPage): string {
  if (page === "apply") {
    return "Visible Chrome apply with live workers and logs.";
  }
  if (page === "applications") {
    return "Submitted applications, failures, and what was filled on each form.";
  }
  if (page === "home") {
    return "ApplyPilot worked overnight. Here's what's new.";
  }
  if (page === "outreach") {
    return "LinkedIn drafts and recruiter replies in the Other tab.";
  }
  if (page === "pipeline") {
    return "What the agent's doing right now and how well";
  }
  if (page === "learning") {
    return "Playbook cache hits, review timeline, and promote/ban controls.";
  }
  if (page === "settings") {
    return "Tune the agent · sources, queries, limits, profile";
  }
  return "Triage new roles, scores, and application status.";
}

/** finalized.html header subtitles with live counts when stats are available. */
export function pageSubtitleWithStats(page: DashboardPage, stats: Stats | undefined): string {
  const p = stats?.pipeline;
  if (page === "jobs") {
    const newPicks = stats?.triage_counts?.new ?? (p?.scored ?? 0) + (p?.unscored ?? 0);
    const ready = stats?.ready_to_apply ?? p?.pending_apply ?? 0;
    return `${newPicks} new picks · ${ready} ready to apply · skip or save the rest`;
  }
  if (page === "applications") {
    const applied = p?.applied ?? 0;
    const needsHelp =
      (p?.submitted_unverified ?? 0) +
      ((stats?.extra?.apply_manual as number | undefined) ?? 0);
    const queued = p?.ready_to_apply ?? 0;
    return `${applied} applied · ${needsHelp} need your help · ${queued} queued`;
  }
  if (page === "outreach") {
    const drafts =
      stats?.extra?.inbox_queue ??
      stats?.extra?.outreach_queue ??
      stats?.extra?.referral_pending_connect ??
      0;
    return `${drafts} drafts ready · LinkedIn DMs sent via your account`;
  }
  return pageSubtitle(page);
}

/** Deep-link slug for Jobs page ?stage= when clicking a pipeline summary card. */
export const PIPELINE_CARD_JOBS_STAGE: Record<PipelineStageId, string> = {
  discover: "discovered",
  enrich: "enriched",
  filter: "rejected",
  score: "scored",
  tailor: "tailored",
  cover: "cover",
  pdf: "ready",
};
