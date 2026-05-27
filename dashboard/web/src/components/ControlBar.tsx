import { useState } from "react";
import type { Run } from "../api";

type Props = {
  isRunning: boolean;
  starting: boolean;
  runType: string;
  onRunTypeChange: (t: string) => void;
  stream: boolean;
  dryRun: boolean;
  minScore: number;
  workers: number;
  onMinScoreChange: (v: number) => void;
  onWorkersChange: (v: number) => void;
  stageOrder: string[];
  selectedStages: string[];
  onToggleStage: (stage: string) => void;
  onSelectAll: () => void;
  onStreamChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;
  onStart: () => void;
  onStop: () => void;
  activeRun: Run | null;
};

const PHASE2_TYPES = [
  { id: "apply", label: "Apply" },
  { id: "refer", label: "Refer" },
  { id: "inbox", label: "Inbox" },
];

const STAGE_LABELS: Record<string, string> = {
  refer: "Refer prep",
};

const STAGE_TITLES: Record<string, string> = {
  refer: "Scrape recruiters and fill message templates only (no OpenOutreach)",
};

export function ControlBar({
  isRunning,
  starting,
  runType,
  onRunTypeChange,
  stream,
  dryRun,
  minScore,
  workers,
  onMinScoreChange,
  onWorkersChange,
  stageOrder,
  selectedStages,
  onToggleStage,
  onSelectAll,
  onStreamChange,
  onDryRunChange,
  onStart,
  onStop,
  activeRun,
}: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const pipelineOnly = runType === "pipeline";

  return (
    <section className="panel p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <label htmlFor="run-type" className="sr-only">
            Run type
          </label>
          <select
            id="run-type"
            value={runType}
            onChange={(e) => onRunTypeChange(e.target.value)}
            disabled={isRunning}
            className="rounded-lg border border-panel-border-strong bg-panel-elevated/80 px-3 py-2 text-sm text-ink-2 shadow-sm outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/40 disabled:opacity-50"
          >
            <option value="pipeline">Pipeline</option>
            {PHASE2_TYPES.map((t) => (
              <option key={t.id} value={t.id} disabled title="Phase 2 — not available in dashboard yet">
                {t.label} (phase 2)
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          disabled={isRunning || starting || !pipelineOnly}
          title={!pipelineOnly ? "Only pipeline runs are supported in the dashboard" : undefined}
          onClick={onStart}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {starting ? "Starting…" : "Run pipeline"}
        </button>
        <button
          type="button"
          disabled={!isRunning}
          onClick={onStop}
          className="rounded-lg border border-panel-border-strong bg-zinc-900/50 px-4 py-2 text-sm text-ink-2 hover:border-zinc-500 hover:bg-panel-muted disabled:cursor-not-allowed disabled:opacity-40"
        >
          Stop
        </button>

        <div className="h-6 w-px bg-zinc-700/80" aria-hidden />

        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-3">
          <input
            type="checkbox"
            checked={stream}
            onChange={(e) => onStreamChange(e.target.checked)}
            disabled={isRunning}
            className="rounded border-panel-border-strong bg-zinc-900 text-blue-500"
          />
          Stream
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-3">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => onDryRunChange(e.target.checked)}
            disabled={isRunning}
            className="rounded border-panel-border-strong bg-zinc-900 text-blue-500"
          />
          Dry run
        </label>

        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          className="text-sm text-blue-400 hover:text-blue-300"
          disabled={isRunning}
        >
          {advancedOpen ? "Hide advanced" : "Advanced"}
        </button>

        {activeRun && (
          <span className="ml-auto text-xs text-ink-4">
            <span className="font-mono text-ink-2">{activeRun.id.slice(0, 8)}</span>
            {" · "}
            <span
              className={
                activeRun.status === "running"
                  ? "text-emerald-400"
                  : activeRun.status === "failed"
                    ? "text-red-400"
                    : "text-ink-2"
              }
            >
              {activeRun.status}
            </span>
          </span>
        )}
      </div>

      {advancedOpen && pipelineOnly && (
        <div className="mt-3 flex flex-wrap items-end gap-4 border-t border-panel-border/80 pt-3">
          <label className="block text-xs text-ink-4">
            Min score
            <input
              type="number"
              min={0}
              max={10}
              value={minScore}
              onChange={(e) => onMinScoreChange(Number(e.target.value))}
              disabled={isRunning}
              className="mt-1 block w-24 rounded-lg border border-panel-border-strong bg-panel-elevated/80 px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs text-ink-4">
            Workers
            <input
              type="number"
              min={1}
              max={32}
              value={workers}
              onChange={(e) => onWorkersChange(Number(e.target.value))}
              disabled={isRunning}
              className="mt-1 block w-24 rounded-lg border border-panel-border-strong bg-panel-elevated/80 px-2 py-1.5 text-sm"
            />
          </label>
        </div>
      )}

      {pipelineOnly && (
        <div className="mt-4 border-t border-panel-border/80 pt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-ink-4">Stages</span>
            <button
              type="button"
              onClick={onSelectAll}
              className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
              disabled={isRunning}
            >
              Select all
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {stageOrder.map((stage) => {
              const on = selectedStages.includes(stage);
              return (
                <button
                  key={stage}
                  type="button"
                  disabled={isRunning}
                  onClick={() => onToggleStage(stage)}
                  title={STAGE_TITLES[stage]}
                  className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
                    on
                      ? "border-blue-500/50 bg-blue-500/15 text-blue-200"
                      : "border-panel-border-strong bg-zinc-900/50 text-ink-4 hover:border-panel-border-strong"
                  }`}
                >
                  {STAGE_LABELS[stage] ?? stage}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
