import type { Job } from "../api";

const MAX_APPLY_ATTEMPTS = 3;
const MAX_TAILOR_ATTEMPTS = 5;

export type PipelineStageFilter = "all" | "tailored" | "ready" | "applied";

/** User-facing label for where a job sits in discover → apply flow. */
export function jobPipelineStage(job: Job): string {
  if (job.apply_status === "in_progress") return "Applying";
  if (job.apply_status === "submitted_unverified") return "Needs check";
  if (job.apply_status === "manual") return "Manual";
  if (job.apply_status === "applied" || (job.applied_at && !job.apply_status)) return "Applied";
  if (isReadyToApply(job)) return "Ready";
  if (job.apply_status === "failed") return "Failed";
  if (job.pre_filter_rejected_at || job.pre_filter_reason) return "Rejected";
  if (job.tailored_resume_path) {
    if (job.cover_letter_path) return "Cover";
    return "Tailored";
  }
  const tailorAttempts = job.tailor_attempts ?? 0;
  if (job.fit_score != null && tailorAttempts >= MAX_TAILOR_ATTEMPTS) {
    return "Tailor exhausted";
  }
  if (job.fit_score != null) return "Scored";
  if (job.full_description) return "Enriched";
  if (job.detail_error) return "Enrich error";
  return "Discovered";
}

export function isReadyToApply(job: Job): boolean {
  if (!job.tailored_resume_path || job.applied_at) return false;
  const status = job.apply_status;
  if (
    status === "manual" ||
    status === "in_progress" ||
    status === "applied" ||
    status === "submitted_unverified"
  ) {
    return false;
  }
  const attempts = job.apply_attempts ?? 0;
  if (attempts >= MAX_APPLY_ATTEMPTS) return false;
  return status == null || status === "failed";
}

/** Subset used by stage filter badges (tailored / ready / applied). */
export function jobPipelineLabel(job: Job): string | null {
  const stage = jobPipelineStage(job);
  if (stage === "Applied") return "Applied";
  if (stage === "Ready") return "Ready";
  if (
    stage === "Tailored" ||
    stage === "Cover" ||
    stage === "Applying" ||
    stage === "Failed" ||
    stage === "Manual"
  ) {
    return "Tailored";
  }
  return null;
}

export function stageBadgeClass(stage: string): string {
  switch (stage) {
    case "Applied":
      return "bg-success/10 text-success border border-success/25";
    case "Ready":
      return "bg-accent-muted text-accent border border-accent/25";
    case "Applying":
      return "bg-accent/10 text-accent-2 border border-accent/20";
    case "Needs check":
    case "Manual":
      return "bg-warning/10 text-warning border border-warning/25";
    case "Failed":
    case "Rejected":
    case "Enrich error":
    case "Tailor exhausted":
      return "bg-danger/10 text-danger border border-danger/25";
    case "Tailored":
    case "Cover":
      return "bg-panel-muted text-ink-2 border border-panel-border-strong";
    case "Scored":
      return "bg-panel-elevated text-ink-3 border border-panel-border";
    case "Enriched":
      return "bg-panel-elevated text-ink-4 border border-panel-border";
    default:
      return "bg-panel-muted text-ink-4 border border-panel-border";
  }
}
