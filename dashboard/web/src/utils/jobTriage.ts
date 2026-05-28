import type { Stats } from "../api";
import type { Job } from "../api";
import { jobPipelineStage } from "./jobPipeline";

/** Jobs list filter chips — display labels match finalized.html; slugs map to API stage filters. */
export const JOB_TRIAGE_FILTERS: { slug: string; label: string }[] = [
  { slug: "", label: "All" },
  { slug: "scored", label: "New" },
  { slug: "tailored", label: "Tailored" },
  { slug: "applied", label: "Submitted" },
  { slug: "failed", label: "Failed" },
  { slug: "ready", label: "Saved" },
  { slug: "discovered", label: "Skipped" },
];

export function triageFilterCount(slug: string, stats: Stats | undefined): number {
  const p = stats?.pipeline;
  const total = stats?.total ?? 0;
  if (!slug) return total;
  if (!p) return 0;
  switch (slug) {
    case "scored":
      return (p.scored ?? 0) + (p.unscored ?? 0);
    case "tailored":
      return stats?.tailored ?? p.tailored ?? 0;
    case "applied":
      return p.applied ?? 0;
    case "failed":
      return p.apply_errors ?? 0;
    case "ready":
      return p.ready_to_apply ?? 0;
    case "discovered":
      return Math.max(0, total - (p.scored ?? 0) - (p.applied ?? 0));
    default:
      return 0;
  }
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
