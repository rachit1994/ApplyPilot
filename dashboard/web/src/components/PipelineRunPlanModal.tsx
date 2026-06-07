import { useMemo } from "react";
import {
  buildPipelineCliCommand,
  pipelineRunSummaryLines,
} from "../utils/pipelineRunPlan";
import { PipelineRunControls, type PipelineRunControlSettings } from "./PipelineRunControls";
import { RunPlanModal } from "./RunPlanModal";

type Props = {
  open: boolean;
  settings: PipelineRunControlSettings;
  onCancel: () => void;
  onConfirm: () => void;
};

export function PipelineRunPlanModal({ open, settings, onCancel, onConfirm }: Props) {
  const runOptions = useMemo(
    () => ({
      selectedStages: settings.selectedStages,
      stageOrder: settings.stageOrder,
      minScore: settings.pipelineMinScore,
      workers: settings.workers,
      stream: settings.stream,
      dryRun: settings.dryRun,
    }),
    [
      settings.selectedStages,
      settings.stageOrder,
      settings.pipelineMinScore,
      settings.workers,
      settings.stream,
      settings.dryRun,
    ],
  );

  const cliCommand = useMemo(() => buildPipelineCliCommand(runOptions), [runOptions]);
  const summaryLines = useMemo(() => pipelineRunSummaryLines(runOptions), [runOptions]);
  const canStart = settings.selectedStages.length > 0 && !settings.isRunning;

  return (
    <RunPlanModal
      open={open}
      title="Start pipeline run"
      subtitle="Pick which stages to run — skip discover to start from enrich."
      cliCommand={cliCommand}
      summaryLines={summaryLines}
      confirmDisabled={!canStart}
      wide
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <PipelineRunControls settings={settings} compact />
      {!canStart && settings.selectedStages.length === 0 ? (
        <p className="run-plan-modal__alert">Select at least one stage to run.</p>
      ) : null}
    </RunPlanModal>
  );
}
