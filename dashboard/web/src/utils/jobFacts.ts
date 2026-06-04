import type { Job } from "../api";

/** Treat null, undefined, and whitespace-only strings as empty for detail UI. */
export function displayJobField(value: string | number | null | undefined): string {
  if (value == null) return "—";
  if (typeof value === "number") return String(value);
  const trimmed = value.trim();
  return trimmed || "—";
}

export function inferRemoteFromLocation(location: string | null | undefined): string | null {
  if (!location?.trim()) return null;
  const loc = location.toLowerCase();
  const hasRemote = loc.includes("remote");
  const hasHybrid = loc.includes("hybrid");
  const hasOnsite =
    loc.includes("onsite") ||
    loc.includes("on-site") ||
    loc.includes("on site") ||
    loc.includes("in-office") ||
    loc.includes("in office") ||
    loc.includes("office-based");
  if (hasRemote && hasHybrid) return "Hybrid";
  if (hasRemote && hasOnsite) return "Mixed";
  if (hasRemote) return "Remote";
  if (hasHybrid) return "Hybrid";
  if (hasOnsite) return "On-site";
  return "On-site";
}

export function formatFitScoreDetail(job: Job): { text: string; accent: boolean } {
  if (job.fit_score != null) {
    return { text: `${job.fit_score}/10`, accent: job.fit_score >= 8 };
  }
  if (job.pre_fit_score != null) {
    return { text: `Pre-score ${job.pre_fit_score}/10`, accent: false };
  }
  if (job.pre_filter_reason) {
    return { text: "Filtered out", accent: false };
  }
  if (job.scored_at) {
    return { text: "Scored (no score stored)", accent: false };
  }
  if (job.full_description) {
    return { text: "Not scored yet", accent: false };
  }
  return { text: "Needs enrich", accent: false };
}

export function formatApplyStatusDetail(job: Job): string {
  if (job.apply_status) return job.apply_status;
  if (job.apply_error) return `Failed: ${job.apply_error}`;
  if (job.applied_at) return "Applied (unverified)";
  if (job.apply_attempts != null && job.apply_attempts > 0) {
    return `Attempted (${job.apply_attempts})`;
  }
  return "Not applied";
}
