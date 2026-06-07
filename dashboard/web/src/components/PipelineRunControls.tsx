import type { ReactNode } from "react";
import {
  PIPELINE_STAGE_IDS,
  STAGE_DESCRIPTIONS,
  STAGE_LABELS,
  type PipelineStageId,
} from "../dashboardNav";
import {
  orderedPipelineStages,
  resolveStageOrder,
  stagesFrom,
} from "../utils/pipelineRunPlan";
import { ToggleSwitch } from "./ToggleSwitch";

export type PipelineRunControlSettings = {
  stageOrder: string[];
  selectedStages: PipelineStageId[];
  toggleStage: (stage: PipelineStageId) => void;
  setSelectedStages: (stages: PipelineStageId[]) => void;
  stream: boolean;
  setStream: (value: boolean) => void;
  dryRun: boolean;
  setDryRun: (value: boolean) => void;
  pipelineMinScore: number;
  setPipelineMinScore: (value: number) => void;
  workers: number;
  setWorkers: (value: number) => void;
  isRunning: boolean;
};

type Props = {
  settings: PipelineRunControlSettings;
  compact?: boolean;
};

const PRESETS: {
  id: string;
  label: string;
  apply: (order: PipelineStageId[]) => PipelineStageId[];
}[] = [
  { id: "full", label: "Full pipeline", apply: (order) => [...order] },
  { id: "from-enrich", label: "From enrich", apply: (order) => stagesFrom("enrich", order) },
  { id: "from-score", label: "From score", apply: (order) => stagesFrom("score", order) },
  {
    id: "tailor-pdf",
    label: "Tailor + PDF",
    apply: (order) => orderedPipelineStages(["tailor", "cover", "pdf"], order),
  },
];

function SetRow({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right: ReactNode;
}) {
  return (
    <div className="set-row">
      <div className="set-row__main">
        <div className="set-row__title">{title}</div>
        {sub ? <div className="set-row__sub">{sub}</div> : null}
      </div>
      <div className="set-row__right">{right}</div>
    </div>
  );
}

function presetIsActive(
  selected: PipelineStageId[],
  order: PipelineStageId[],
  presetStages: PipelineStageId[],
): boolean {
  const current = orderedPipelineStages(selected, order);
  const target = orderedPipelineStages(presetStages, order);
  if (current.length !== target.length) return false;
  return current.every((stage, index) => stage === target[index]);
}

export function PipelineRunControls({ settings }: Props) {
  const order = resolveStageOrder(settings.stageOrder);
  const disabled = settings.isRunning;

  return (
    <>
      <section className="run-plan-modal__section">
        <div className="set-section-header">
          <div className="set-section-title">Pipeline stages</div>
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            disabled={disabled}
            onClick={() => settings.setSelectedStages([...PIPELINE_STAGE_IDS])}
          >
            Select all
          </button>
        </div>
        <p className="run-plan-modal__section-hint">
          Uncheck stages to skip them. Order matches the CLI — start at enrich without running
          discover.
        </p>
        <div className="run-plan-modal__presets">
          {PRESETS.map((preset) => {
            const presetStages = preset.apply(order);
            const on = presetIsActive(settings.selectedStages, order, presetStages);
            return (
              <button
                key={preset.id}
                type="button"
                disabled={disabled}
                onClick={() => settings.setSelectedStages(presetStages)}
                className={on ? "chip chip--on" : "chip"}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
        <div className="set-group">
          {order.map((stage) => {
            const on = settings.selectedStages.includes(stage);
            return (
              <button
                key={stage}
                type="button"
                disabled={disabled}
                className={on ? "run-plan-stage run-plan-stage--on" : "run-plan-stage"}
                onClick={() => settings.toggleStage(stage)}
                aria-pressed={on}
              >
                <div className="set-row__main">
                  <div className="set-row__title">{STAGE_LABELS[stage]}</div>
                  <div className="set-row__sub">{STAGE_DESCRIPTIONS[stage]}</div>
                </div>
                <span className="run-plan-stage__mark" aria-hidden />
              </button>
            );
          })}
        </div>
      </section>

      <section className="run-plan-modal__section">
        <div className="set-section-title">Run options</div>
        <div className="set-group">
          <SetRow
            title="Minimum score"
            sub="Only jobs at or above this fit score enter the run"
            right={
              <label className="select-val select-val--input">
                <span className="visually-hidden">Minimum score</span>
                <input
                  type="number"
                  className="select-val__field"
                  min={0}
                  max={10}
                  disabled={disabled}
                  value={settings.pipelineMinScore}
                  onChange={(e) => settings.setPipelineMinScore(Number(e.target.value))}
                />
              </label>
            }
          />
          <SetRow
            title="Workers"
            sub="Parallel workers for scoring and tailoring stages"
            right={
              <label className="select-val select-val--input">
                <span className="visually-hidden">Workers</span>
                <input
                  type="number"
                  className="select-val__field"
                  min={1}
                  max={8}
                  disabled={disabled}
                  value={settings.workers}
                  onChange={(e) => settings.setWorkers(Number(e.target.value))}
                />
              </label>
            }
          />
          <SetRow
            title="Stream logs to dashboard"
            sub="Live updates in the pipeline and Today views"
            right={
              <ToggleSwitch
                label="Stream logs to dashboard"
                on={settings.stream}
                disabled={disabled}
                onChange={settings.setStream}
              />
            }
          />
          <SetRow
            title="Dry run"
            sub="Exercise the flow without writing to the database"
            right={
              <ToggleSwitch
                label="Dry run"
                on={settings.dryRun}
                disabled={disabled}
                onChange={settings.setDryRun}
              />
            }
          />
        </div>
      </section>
    </>
  );
}
