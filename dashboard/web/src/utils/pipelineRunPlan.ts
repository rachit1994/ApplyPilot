import {
  PIPELINE_STAGE_IDS,
  STAGE_DESCRIPTIONS,
  STAGE_LABELS,
  type PipelineStageId,
} from "../dashboardNav";

export type PipelineRunOptions = {
  selectedStages: PipelineStageId[];
  stageOrder: string[];
  minScore: number;
  workers: number;
  stream: boolean;
  dryRun: boolean;
};

export function resolveStageOrder(stageOrder: string[]): PipelineStageId[] {
  if (stageOrder.length > 0) {
    return stageOrder.filter((s): s is PipelineStageId =>
      (PIPELINE_STAGE_IDS as readonly string[]).includes(s),
    );
  }
  return [...PIPELINE_STAGE_IDS];
}

export function orderedPipelineStages(
  selected: PipelineStageId[],
  stageOrder: string[],
): PipelineStageId[] {
  const order = resolveStageOrder(stageOrder);
  return order.filter((s) => selected.includes(s));
}

export function stagesFrom(
  startStage: PipelineStageId,
  stageOrder: string[],
): PipelineStageId[] {
  const order = resolveStageOrder(stageOrder);
  const idx = order.indexOf(startStage);
  if (idx < 0) return [...PIPELINE_STAGE_IDS];
  return order.slice(idx);
}

export function buildPipelineCliCommand(opts: PipelineRunOptions): string {
  const stages = orderedPipelineStages(opts.selectedStages, opts.stageOrder);
  const parts = ["applypilot", "run", ...stages];
  parts.push("--min-score", String(opts.minScore));
  parts.push("--workers", String(opts.workers));
  if (opts.stream) parts.push("--stream");
  if (opts.dryRun) parts.push("--dry-run");
  return parts.join(" ");
}

export function pipelineRunSummaryLines(opts: PipelineRunOptions): string[] {
  const stages = orderedPipelineStages(opts.selectedStages, opts.stageOrder);
  const stageNames =
    stages.length > 0
      ? stages.map((s) => STAGE_LABELS[s]).join(" → ")
      : "None selected";
  const lines = [`Stages: ${stageNames}`, `Min score ${opts.minScore} · ${opts.workers} worker(s)`];
  if (opts.stream) lines.push("Live stream to dashboard");
  if (opts.dryRun) lines.push("Dry run — no database writes");
  return lines;
}

export { STAGE_DESCRIPTIONS, STAGE_LABELS };
