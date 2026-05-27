import type { Run } from "../../api";
import type { StageProgressSnapshot, StageState } from "../../utils/stageProgress";
import { formatStageProgressLine } from "../../utils/stageProgress";

type Props = {
  activeRun: Run | null;
  isRunning: boolean;
  currentStage: string | null;
  stageStates: Record<string, StageState>;
  workers: number;
  progressSnap?: StageProgressSnapshot | null;
  focusStage?: string;
};

export function NowPanel({
  activeRun,
  isRunning,
  currentStage,
  stageStates,
  workers,
  progressSnap,
  focusStage,
}: Props) {
  const activeStages = Object.entries(stageStates).filter(([, s]) => s === "active");
  const detailLine = formatStageProgressLine(progressSnap ?? null);
  const percent =
    progressSnap?.percent != null
      ? `${progressSnap.percent}%`
      : progressSnap?.done != null && progressSnap?.total
        ? `${progressSnap.done}/${progressSnap.total}`
        : null;

  return (
    <section className="rounded-[var(--rad-card)] border border-panel-border bg-panel p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Now</h2>
        <span
          className={`inline-flex items-center gap-1.5 rounded-[var(--rad-chip)] px-2 py-0.5 text-[10px] font-medium ${
            isRunning
              ? "bg-accent/15 text-accent"
              : "border border-panel-border text-ink-4"
          }`}
        >
          {isRunning ? (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
          ) : null}
          {isRunning ? "Running" : activeRun?.status ?? "Idle"}
        </span>
      </div>

      <p className="mt-3 font-mono text-sm text-ink">
        {isRunning
          ? detailLine ??
            (currentStage ? `Stage: ${currentStage}` : "Running…")
          : activeRun?.status === "failed"
            ? activeRun.error_message ?? "Run failed"
            : "No active run — use Run plan to start."}
      </p>

      {isRunning && percent ? (
        <div className="mt-3">
          <div className="flex justify-between text-[10px] text-ink-4">
            <span>{focusStage ?? currentStage ?? "progress"}</span>
            <span className="font-mono tabular-nums">{percent}</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-panel-border">
            <div
              className="h-full bg-accent transition-all duration-300"
              style={{ width: `${Math.min(100, progressSnap?.percent ?? 5)}%` }}
            />
          </div>
        </div>
      ) : null}

      {workers > 1 ? (
        <p className="mt-2 text-xs text-ink-3">{workers} workers configured</p>
      ) : null}

      {activeStages.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {activeStages.map(([st]) => (
            <li
              key={st}
              className="rounded-[var(--rad-chip)] border border-panel-border bg-panel-elevated px-2 py-1 text-[10px] text-ink-2"
            >
              {st}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
