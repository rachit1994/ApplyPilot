import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStats } from "../api";
import { useApplyRun } from "../hooks/useApplyRun";
import { LogConsole } from "./LogConsole";
import { RunBanner } from "./RunBanner";
import { RunPlanModal } from "./RunPlanModal";
import { PriorityBoardsBanner } from "./PriorityBoardsBanner";
import { WorkerChip } from "./pipeline/WorkerChip";

type Props = {
  unverifiedCount?: number;
  onOpenApplications?: (params?: Record<string, string>) => void;
};

type WorkerHeartbeatPayload = {
  worker_id?: number;
  detail?: string;
  status?: string;
};

export function ApplyPage({ unverifiedCount = 0, onOpenApplications }: Props) {
  const run = useApplyRun();
  const [showPlan, setShowPlan] = useState(false);
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });

  const pipeline = stats?.pipeline ?? {};
  const unverified = unverifiedCount ?? pipeline.submitted_unverified ?? 0;
  const appliedCount = stats?.applied ?? 0;

  const workerChips = useMemo(() => {
    const latest = new Map<number, { detail: string; status?: string; at?: string }>();
    for (const e of run.workerHeartbeats) {
      const payload = e.payload as WorkerHeartbeatPayload;
      const id = Number(payload.worker_id ?? 0);
      const detail = String(payload.detail ?? e.message ?? "");
      latest.set(id, { detail, status: payload.status, at: e.created_at });
    }
    return [...latest.entries()].sort((a, b) => a[0] - b[0]);
  }, [run.workerHeartbeats]);

  const cliPreview = useMemo(() => {
    const parts = ["applypilot", "apply"];
    if (run.limit !== "") parts.push("--limit", String(run.limit));
    parts.push("--min-score", String(run.minScore));
    parts.push("--workers", String(run.workers));
    if (run.watch) parts.push("--watch");
    if (run.pace) parts.push("--pace");
    if (run.headless) parts.push("--headless");
    if (run.continuous) parts.push("--continuous");
    if (run.dryRun) parts.push("--dry-run");
    return parts.join(" ");
  }, [run]);

  return (
    <div className="space-y-6 pb-8">
      {run.error ? (
        <div role="alert" className="rounded-card border border-bad/40 bg-bad/10 px-4 py-3 text-sm">
          {run.error}
        </div>
      ) : null}

      {onOpenApplications && (appliedCount > 0 || unverified > 0) ? (
        <button
          type="button"
          onClick={() =>
            onOpenApplications(unverified > 0 ? { filter: "unverified" } : undefined)
          }
          className="flex w-full items-center justify-between gap-3 rounded-card border border-panel-border bg-panel px-4 py-3 text-left text-sm transition-colors hover:border-accent/40 hover:bg-panel-elevated"
        >
          <span className="text-ink">
            Review <strong>{appliedCount}</strong> application
            {appliedCount === 1 ? "" : "s"}
            {unverified > 0 ? (
              <>
                {" "}
                — <span className="text-warn">{unverified} need verification</span>
              </>
            ) : null}
          </span>
          <span className="shrink-0 text-accent">Open ledger →</span>
        </button>
      ) : null}

      <RunBanner run={run.activeRun} />

      <PriorityBoardsBanner
        compact
        priorityBoards={stats?.priority_boards}
        applyQueueOrder={stats?.apply_queue_order}
      />

      <section className="panel p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <h2 className="font-display text-base text-ink">Apply run</h2>
            <p className="text-xs text-ink-3">Visible Chrome by default — use watch + pace.</p>
          </div>
          <button
            type="button"
            disabled={run.isRunning || run.starting}
            onClick={() => setShowPlan(true)}
            className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90 disabled:opacity-40"
          >
            {run.starting ? "Starting…" : "Run apply"}
          </button>
          <button
            type="button"
            disabled={!run.isRunning}
            onClick={() => void run.handleStop()}
            className="rounded-btn border border-bad/50 bg-bad/10 px-4 py-2 text-sm text-bad disabled:opacity-40"
          >
            Stop
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-4 text-xs text-ink-3">
          <span>
            Applied: <strong className="text-ink">{stats?.applied ?? "—"}</strong>
          </span>
          <span>
            Unverified: <strong className="text-warn">{unverified}</strong>
          </span>
          <span>
            Ready: <strong className="text-ink">{stats?.ready_to_apply ?? "—"}</strong>
          </span>
        </div>
      </section>

      {run.isRunning && workerChips.length > 0 ? (
        <section className="rounded-card border border-panel-border bg-panel p-4">
          <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Workers</h3>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {workerChips.map(([id, info]) => {
              const detail = info.detail || "…";
              const paused = info.status === "paused_quota";
              return (
                <li key={id} className="list-none">
                  <WorkerChip
                    id={`W${id}`}
                    title={`Worker ${id}`}
                    ats="apply"
                    subStep={detail}
                    elapsed="—"
                    costSoFar="—"
                    active={run.isRunning && !paused}
                    paused={paused}
                    statusVariant={paused ? "needs-check" : "running"}
                  />
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {run.isRunning ? (
        <section className="rounded-card border border-panel-border bg-panel p-2">
          <LogConsole events={run.events} errors={run.errors} />
        </section>
      ) : null}

      <RunPlanModal
        open={showPlan}
        title="Start apply run"
        cliCommand={cliPreview}
        summaryLines={[
          `Ready to apply: ${stats?.ready_to_apply ?? "—"} jobs (≥${run.minScore} score)`,
          `Queue order: ${stats?.apply_queue_order ?? "Naukri → Wellfound → ATS → other"}`,
          `${run.workers} worker(s)`,
          run.watch ? "Visible browser (--watch)" : "Headless unless --headless set",
        ]}
        onCancel={() => setShowPlan(false)}
        onConfirm={() => {
          setShowPlan(false);
          void run.handleStart();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-ink-3">
            Limit
            <input
              type="number"
              min={1}
              value={run.limit}
              onChange={(e) =>
                run.setLimit(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="mt-1 w-full rounded border border-panel-border bg-canvas px-2 py-1 text-sm text-ink"
              placeholder="no limit"
            />
          </label>
          <label className="text-xs text-ink-3">
            Min score
            <input
              type="number"
              min={0}
              max={10}
              value={run.minScore}
              onChange={(e) => run.setMinScore(Number(e.target.value))}
              className="mt-1 w-full rounded border border-panel-border bg-canvas px-2 py-1 text-sm text-ink"
            />
          </label>
          <label className="text-xs text-ink-3">
            Workers
            <input
              type="number"
              min={1}
              max={8}
              value={run.workers}
              onChange={(e) => run.setWorkers(Number(e.target.value))}
              className="mt-1 w-full rounded border border-panel-border bg-canvas px-2 py-1 text-sm text-ink"
            />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-sm text-ink-3">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={run.watch} onChange={(e) => run.setWatch(e.target.checked)} />
            Watch
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={run.pace} onChange={(e) => run.setPace(e.target.checked)} />
            Pace
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={run.headless}
              onChange={(e) => run.setHeadless(e.target.checked)}
            />
            Headless
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={run.continuous}
              onChange={(e) => run.setContinuous(e.target.checked)}
            />
            Continuous
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={run.dryRun} onChange={(e) => run.setDryRun(e.target.checked)} />
            Dry run
          </label>
        </div>
      </RunPlanModal>
    </div>
  );
}
