import type { Run } from "../api";
import { STAGE_LABELS, type PipelineStageId } from "../dashboardNav";

type Props = {
  stage: PipelineStageId;
  isRunning: boolean;
  starting: boolean;
  stream: boolean;
  dryRun: boolean;
  minScore: number;
  workers: number;
  onMinScoreChange: (v: number) => void;
  onWorkersChange: (v: number) => void;
  onStreamChange: (v: boolean) => void;
  onDryRunChange: (v: boolean) => void;
  onStart: () => void;
  onStop: () => void;
  activeRun: Run | null;
  runOnOtherStage?: boolean;
};

export function StageControlBar({
  stage,
  isRunning,
  starting,
  stream,
  dryRun,
  minScore,
  workers,
  onMinScoreChange,
  onWorkersChange,
  onStreamChange,
  onDryRunChange,
  onStart,
  onStop,
  activeRun,
  runOnOtherStage,
}: Props) {
  const label = STAGE_LABELS[stage];
  const blocked = isRunning && runOnOtherStage;

  return (
    <section className="panel p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h2 className="font-display text-base text-ink">{label}</h2>
          <p className="text-xs text-ink-3">
            Runs only <span className="font-mono text-ink-2">{stage}</span> via{" "}
            <span className="font-mono text-ink-2">applypilot run {stage}</span>
          </p>
        </div>

        <button
          type="button"
          disabled={isRunning || starting || blocked}
          title={blocked ? "Another stage is running — stop it first" : undefined}
          onClick={onStart}
          className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {starting ? "Starting…" : `Run ${label.toLowerCase()}`}
        </button>
        <button
          type="button"
          disabled={!isRunning || blocked}
          onClick={onStop}
          className="rounded-btn border border-bad/50 bg-bad/10 px-4 py-2 text-sm text-bad hover:bg-bad/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Stop
        </button>

        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-3">
          <input
            type="checkbox"
            checked={stream}
            onChange={(e) => onStreamChange(e.target.checked)}
            disabled={isRunning}
            className="rounded border-panel-border bg-panel text-accent"
          />
          Stream
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-3">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => onDryRunChange(e.target.checked)}
            disabled={isRunning}
            className="rounded border-panel-border bg-panel text-accent"
          />
          Dry run
        </label>

        <label className="block text-xs text-ink-4">
          Min score
          <input
            type="number"
            min={0}
            max={10}
            value={minScore}
            onChange={(e) => onMinScoreChange(Number(e.target.value))}
            disabled={isRunning}
            className="mt-1 block w-20 rounded-btn border border-panel-border bg-panel px-2 py-1.5 text-sm tabular-nums"
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
            className="mt-1 block w-20 rounded-btn border border-panel-border bg-panel px-2 py-1.5 text-sm tabular-nums"
          />
        </label>

        {activeRun ? (
          <span className="ml-auto text-xs text-ink-4">
            <span className="font-mono text-ink-2">{activeRun.id.slice(0, 8)}</span>
            {" · "}
            <span
              className={
                activeRun.status === "running"
                  ? "text-ok"
                  : activeRun.status === "failed"
                    ? "text-bad"
                    : "text-ink-2"
              }
            >
              {activeRun.status}
            </span>
            {activeRun.current_stage ? (
              <>
                {" · "}
                <span className="text-accent">{activeRun.current_stage}</span>
              </>
            ) : null}
          </span>
        ) : null}
      </div>
    </section>
  );
}
