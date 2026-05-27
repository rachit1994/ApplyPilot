import type { Stats } from "../api";
import type { PipelineStageId } from "../dashboardNav";

/** Pending work count shown on Home stage cards (null = show total jobs instead). */
export function stagePendingCount(
  stage: PipelineStageId,
  stats: Stats | undefined,
): number | null {
  if (!stats) return null;
  const p = stats.pipeline ?? {};
  switch (stage) {
    case "discover":
      return null;
    case "enrich":
      return p.pending_detail ?? null;
    case "score":
      return p.unscored ?? null;
    case "tailor":
      return p.untailored_eligible ?? null;
    case "cover": {
      const tailored = stats.tailored ?? 0;
      const withCover = p.with_cover_letter ?? 0;
      return Math.max(0, tailored - withCover);
    }
    case "pdf": {
      const tailored = stats.tailored ?? 0;
      const ready = stats.ready_to_apply ?? 0;
      return Math.max(0, tailored - ready);
    }
    default:
      return null;
  }
}

export function stagePendingLabel(stage: PipelineStageId, stats: Stats | undefined): string {
  const pending = stagePendingCount(stage, stats);
  if (stage === "discover") {
    return `${stats?.total ?? 0} jobs in DB`;
  }
  if (pending == null) return "—";
  if (pending === 0) return "Nothing pending";
  return `${pending} pending`;
}
