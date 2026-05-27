import type { Job } from "../api";
import { jobPipelineStage } from "./jobPipeline";

export type JobColumnId =
  | "fit_score"
  | "stage"
  | "title"
  | "site"
  | "location"
  | "activity_at"
  | "tailored_resume_path"
  | "cover_letter_path"
  | "discovered_at"
  | "strategy"
  | "detail_error"
  | "detail_scraped_at"
  | "application_url"
  | "scored_at"
  | "score_reasoning"
  | "tailored_at"
  | "tailor_attempts"
  | "cover_letter_at"
  | "cover_attempts"
  | "apply_status"
  | "applied_at"
  | "apply_error"
  | "apply_attempts"
  | "last_attempted_at"
  | "verification_confidence";

export type JobColumnDef = {
  id: JobColumnId;
  label: string;
  minWidth: string;
};

const ALWAYS: JobColumnId[] = [
  "fit_score",
  "stage",
  "title",
  "site",
  "location",
  "activity_at",
  "tailored_resume_path",
  "cover_letter_path",
];

const DISCOVER: JobColumnId[] = ["discovered_at", "strategy"];
const ENRICH: JobColumnId[] = ["detail_error", "detail_scraped_at", "application_url"];
const SCORE: JobColumnId[] = ["scored_at", "score_reasoning"];
const TAILOR: JobColumnId[] = ["tailored_at", "tailor_attempts"];
const COVER: JobColumnId[] = ["cover_letter_at", "cover_attempts"];
const APPLY: JobColumnId[] = [
  "apply_status",
  "applied_at",
  "apply_error",
  "apply_attempts",
  "last_attempted_at",
  "verification_confidence",
];

export const JOB_COLUMN_DEFS: Record<JobColumnId, JobColumnDef> = {
  fit_score: { id: "fit_score", label: "Score", minWidth: "3.5rem" },
  stage: { id: "stage", label: "Stage", minWidth: "6.5rem" },
  title: { id: "title", label: "Title", minWidth: "minmax(12rem, 1fr)" },
  site: { id: "site", label: "Site", minWidth: "7rem" },
  location: { id: "location", label: "Location", minWidth: "7rem" },
  activity_at: { id: "activity_at", label: "Activity", minWidth: "5.5rem" },
  tailored_resume_path: { id: "tailored_resume_path", label: "Resume path", minWidth: "10rem" },
  cover_letter_path: { id: "cover_letter_path", label: "Cover path", minWidth: "10rem" },
  discovered_at: { id: "discovered_at", label: "Discovered", minWidth: "5.5rem" },
  strategy: { id: "strategy", label: "Strategy", minWidth: "5rem" },
  detail_error: { id: "detail_error", label: "Enrich err", minWidth: "8rem" },
  detail_scraped_at: { id: "detail_scraped_at", label: "Enriched at", minWidth: "5.5rem" },
  application_url: { id: "application_url", label: "Apply URL", minWidth: "8rem" },
  scored_at: { id: "scored_at", label: "Scored", minWidth: "5.5rem" },
  score_reasoning: { id: "score_reasoning", label: "Score note", minWidth: "10rem" },
  tailored_at: { id: "tailored_at", label: "Tailored", minWidth: "5.5rem" },
  tailor_attempts: { id: "tailor_attempts", label: "Tailor #", minWidth: "4rem" },
  cover_letter_at: { id: "cover_letter_at", label: "Cover at", minWidth: "5.5rem" },
  cover_attempts: { id: "cover_attempts", label: "Cover #", minWidth: "4rem" },
  apply_status: { id: "apply_status", label: "Apply status", minWidth: "6rem" },
  applied_at: { id: "applied_at", label: "Applied", minWidth: "5.5rem" },
  apply_error: { id: "apply_error", label: "Apply error", minWidth: "10rem" },
  apply_attempts: { id: "apply_attempts", label: "Apply #", minWidth: "4rem" },
  last_attempted_at: { id: "last_attempted_at", label: "Last try", minWidth: "5.5rem" },
  verification_confidence: {
    id: "verification_confidence",
    label: "Verified",
    minWidth: "5rem",
  },
};

function includesStage(filterStage: string, labels: string[]): boolean {
  if (!filterStage || filterStage === "all") return true;
  return labels.includes(filterStage);
}

/** Which optional column groups are visible for the current stage filter slug. */
export function visibleJobColumns(filterStageSlug: string): JobColumnDef[] {
  const filterLabel = stageSlugToDisplayLabel(filterStageSlug);
  const ids: JobColumnId[] = [...ALWAYS];

  if (includesStage(filterLabel, ["All", "Discovered"])) {
    ids.push(...DISCOVER);
  }
  if (includesStage(filterLabel, ["All", "Enriched", "Enrich error"])) {
    ids.push(...ENRICH);
  }
  if (
    includesStage(filterLabel, [
      "All",
      "Scored",
      "Tailor exhausted",
    ])
  ) {
    ids.push(...SCORE);
  }
  if (
    includesStage(filterLabel, [
      "All",
      "Tailored",
      "Cover",
      "Ready",
      "Applying",
      "Needs check",
      "Applied",
      "Failed",
      "Manual",
    ])
  ) {
    ids.push(...TAILOR);
  }
  if (
    includesStage(filterLabel, [
      "All",
      "Cover",
      "Ready",
      "Applying",
      "Needs check",
      "Applied",
      "Failed",
      "Manual",
    ])
  ) {
    ids.push(...COVER);
  }
  if (
    includesStage(filterLabel, [
      "All",
      "Ready",
      "Applying",
      "Needs check",
      "Applied",
      "Failed",
      "Manual",
    ])
  ) {
    ids.push(...APPLY);
  }

  const seen = new Set<JobColumnId>();
  const unique: JobColumnId[] = [];
  for (const id of ids) {
    if (!seen.has(id)) {
      seen.add(id);
      unique.push(id);
    }
  }
  return unique.map((id) => JOB_COLUMN_DEFS[id]);
}

export function gridTemplateColumns(columns: JobColumnDef[]): string {
  return columns.map((c) => c.minWidth).join(" ");
}

export const JOB_STAGE_FILTER_OPTIONS: { slug: string; label: string }[] = [
  { slug: "", label: "All" },
  { slug: "discovered", label: "Discovered" },
  { slug: "enriched", label: "Enriched" },
  { slug: "enrich_error", label: "Enrich error" },
  { slug: "scored", label: "Scored" },
  { slug: "tailored", label: "Tailored" },
  { slug: "cover", label: "Cover" },
  { slug: "ready", label: "Ready" },
  { slug: "applying", label: "Applying" },
  { slug: "needs_check", label: "Needs check" },
  { slug: "applied", label: "Applied" },
  { slug: "failed", label: "Failed" },
  { slug: "manual", label: "Manual" },
  { slug: "tailor_exhausted", label: "Tailor exhausted" },
];

export function stageSlugToDisplayLabel(slug: string): string {
  if (!slug) return "All";
  const hit = JOB_STAGE_FILTER_OPTIONS.find((o) => o.slug === slug);
  return hit?.label ?? slug;
}

export function displayLabelToStageSlug(label: string): string {
  const hit = JOB_STAGE_FILTER_OPTIONS.find((o) => o.label === label);
  return hit?.slug ?? label.toLowerCase().replace(/\s+/g, "_");
}

export function cellValue(job: Job, columnId: JobColumnId): string {
  switch (columnId) {
    case "stage":
      return jobPipelineStage(job);
    case "fit_score":
      return job.fit_score != null ? String(job.fit_score) : "—";
    case "tailor_attempts":
    case "cover_attempts":
    case "apply_attempts":
      return String((job[columnId] as number | null | undefined) ?? "—");
    default: {
      const raw = job[columnId as keyof Job];
      if (raw == null || raw === "") return "—";
      return String(raw);
    }
  }
}
