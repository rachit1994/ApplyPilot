import type { Stats } from "../api";
import type { Job } from "../api";
import { jobPipelineStage } from "./jobPipeline";

/** Jobs tab filter chips — slugs must match server job_triage.TRIAGE_SLUGS. */
export const JOB_TRIAGE_FILTERS: { slug: string; label: string }[] = [
  { slug: "", label: "All" },
  { slug: "new", label: "New" },
  { slug: "rejected", label: "Rejected" },
  { slug: "tailored", label: "Tailored" },
  { slug: "applied", label: "Submitted" },
  { slug: "failed", label: "Failed" },
  { slug: "ready", label: "Saved" },
  { slug: "pending_score", label: "Not scored" },
];

/** Map legacy ?stage= values from bookmarks to current triage slugs. */
export function normalizeTriageStageParam(stage: string): string {
  const raw = stage.trim().toLowerCase();
  if (!raw) return "";
  if (raw === "scored") return "new";
  if (raw === "submitted") return "applied";
  if (raw === "saved") return "ready";
  if (raw === "not_scored" || raw === "discovered") return "pending_score";
  return stage.trim();
}

export function triageFilterCount(
  slug: string,
  counts: Record<string, number> | undefined,
  stats?: Stats,
): number {
  const key = slug ? normalizeTriageStageParam(slug) : "all";
  if (counts) return counts[key] ?? 0;
  if (!slug) return stats?.total ?? 0;
  return 0;
}

/** User-facing status label on job rows (finalized.html). */
export function jobTriageLabel(job: Job): string {
  const stage = jobPipelineStage(job);
  switch (stage) {
    case "Applied":
      return "Submitted";
    case "Failed":
      return "Failed";
    case "Tailored":
    case "Cover":
    case "Ready":
      return "Tailored";
    case "Manual":
    case "Needs check":
      return "Manual";
    case "Rejected":
      return "Rejected";
    case "Scored":
    case "Enriched":
    case "Discovered":
    case "Enrich error":
    case "Applying":
      return "New";
    default:
      return stage;
  }
}

export function parseScoreGe8Subtitle(subtitle: string | null | undefined): number | null {
  if (!subtitle) return null;
  const m = subtitle.match(/(\d+)\s+score\s*≥\s*8/i);
  return m ? Number(m[1]) : null;
}
