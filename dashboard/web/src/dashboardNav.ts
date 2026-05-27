import type { Job } from "./api";
import { jobPipelineStage } from "./utils/jobPipeline";

/** Run pipeline stages (CLI / API), not dashboard pages. */
export const PIPELINE_STAGE_IDS = [
  "discover",
  "enrich",
  "score",
  "tailor",
  "cover",
  "pdf",
] as const;

export type PipelineStageId = (typeof PIPELINE_STAGE_IDS)[number];

export type DashboardPage = "home" | "jobs" | "apply" | "applications";

export const STAGE_LABELS: Record<PipelineStageId, string> = {
  discover: "Discover",
  enrich: "Enrich",
  score: "Score",
  tailor: "Tailor",
  cover: "Cover",
  pdf: "PDF",
};

export const STAGE_DESCRIPTIONS: Record<PipelineStageId, string> = {
  discover: "Job discovery — JobSpy, Workday, feeds, and smart extract.",
  enrich: "Pull full descriptions and application URLs for new jobs.",
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
    value === "applications"
  );
}

const STAGE_JOB_LABELS: Record<PipelineStageId, string[]> = {
  discover: ["Discovered"],
  enrich: ["Enriched", "Enrich error"],
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

export function pageTitle(page: DashboardPage): string {
  if (page === "apply") return "Apply";
  if (page === "applications") return "Applications";
  if (page === "jobs") return "Jobs";
  return "Home";
}

export function pageSubtitle(page: DashboardPage): string {
  if (page === "apply") {
    return "Run visible auto-apply with live workers and logs.";
  }
  if (page === "applications") {
    return "Audit what was filled, why apply failed, and submit proof.";
  }
  if (page === "home") {
    return "Mission control — summary, run controls, and deep links into Jobs.";
  }
  return "Paginated job explorer with stage filters and resume/cover paths.";
}

/** Deep-link slug for Jobs page ?stage= when clicking a pipeline summary card. */
export const PIPELINE_CARD_JOBS_STAGE: Record<PipelineStageId, string> = {
  discover: "discovered",
  enrich: "enrich_error",
  score: "scored",
  tailor: "tailored",
  cover: "cover",
  pdf: "ready",
};
