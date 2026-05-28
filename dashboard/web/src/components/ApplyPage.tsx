import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStats } from "../api";
import { useApplyRun } from "../hooks/useApplyRun";
import { summarizeWorkers, workerStatusLabel, workerStatusbarClass } from "../utils/applyRunState";
import { LogConsole } from "./LogConsole";

type Props = {
  unverifiedCount?: number;
  onOpenApplications?: (params?: Record<string, string>) => void;
};

export function ApplyPage({ unverifiedCount = 0, onOpenApplications }: Props) {
  const run = useApplyRun();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });

  const pipeline = stats?.pipeline ?? {};
  const unverified = unverifiedCount ?? pipeline.submitted_unverified ?? 0;
  const appliedCount = stats?.applied ?? 0;
  const agent = run.agentState;
  const workerSummary = useMemo(
    () => summarizeWorkers(run.workerSnapshots),
    [run.workerSnapshots],
  );

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
    <>
      <section className="runband apply-runband" aria-label="Apply Queue">
        <div className="runband__status">
          {agent.pulse ? <span className="runband__pulse" aria-hidden /> : null}
          <div>
            <div className="runband__label">
              <span className={agent.statusbarClassName}>{agent.label}</span>
            </div>
            <div className="runband__title">Apply agent</div>
            <div className="runband__sub">{agent.subtitle}</div>
            {run.error || run.activeRun?.error_message ? (
              <div className="runband__sub" style={{ color: "var(--warn)", marginTop: 6 }}>
                {run.error ?? run.activeRun?.error_message}
              </div>
            ) : null}
          </div>
        </div>
        <div className="runband__controls">
          <button
            type="button"
            className="btn btn--accent"
            disabled={run.isRunning || run.starting}
            onClick={() => void run.handleStart()}
          >
            {run.starting ? "Starting…" : "Run apply"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!run.isRunning}
            onClick={() => void run.handleStop()}
          >
            Stop
          </button>
          {onOpenApplications ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => onOpenApplications(unverified > 0 ? { filter: "unverified" } : undefined)}
            >
              Review applications
            </button>
          ) : null}
        </div>
        <div className="runband__metrics">
          <div className="kpi">
            <div className="kpi__label">Ready</div>
            <div className="kpi__value">{stats?.ready_to_apply ?? "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Applied</div>
            <div className="kpi__value">{appliedCount ?? "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Unverified</div>
            <div className="kpi__value">{unverified ?? "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Errors</div>
            <div className="kpi__value">{run.errors.length}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Workers</div>
            <div className="kpi__value">{run.workers}</div>
          </div>
        </div>
      </section>

      <section className="kpis apply-kpis" aria-label="Apply KPIs">
        <div className="kpi">
          <div className="kpi__label">Ready to apply</div>
          <div className="kpi__value">{stats?.ready_to_apply ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Applied today</div>
          <div className="kpi__value">{appliedCount ?? "—"}</div>
        </div>
        <div className={`kpi ${unverified > 0 ? "kpi--attn" : ""}`}>
          <div className="kpi__label">Needs verify</div>
          <div className="kpi__value">{unverified ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Failed</div>
          <div className="kpi__value">{pipeline.apply_errors ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Worker count</div>
          <div className="kpi__value">{run.workers}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Mode</div>
          <div className="kpi__value">{run.watch ? "watch" : run.headless ? "headless" : "visible"}</div>
        </div>
      </section>

      <section className="panel apply-controls" aria-label="Run controls">
        <div className="panel__head">
          <div>
            <div className="panel__title">Run controls</div>
            <div className="panel__sub">Visible Chrome by default · use watch + pace</div>
          </div>
        </div>
        <div className="panel__body">
          <div className="panel__meta font-mono text-xs">{cliPreview}</div>

          <div className="control-grid mt-10">
            <label className="control">
              <span className="control__label">Limit</span>
              <input
                className="control__input"
                type="number"
                min={1}
                value={run.limit}
                onChange={(e) => run.setLimit(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="no limit"
              />
            </label>
            <label className="control">
              <span className="control__label">Min score</span>
              <input
                className="control__input"
                type="number"
                min={0}
                max={10}
                value={run.minScore}
                onChange={(e) => run.setMinScore(Number(e.target.value))}
              />
            </label>
            <label className="control">
              <span className="control__label">Workers</span>
              <input
                className="control__input"
                type="number"
                min={1}
                max={8}
                value={run.workers}
                onChange={(e) => run.setWorkers(Number(e.target.value))}
              />
            </label>
          </div>

          <div className="mt-10 flex flex-wrap gap-8">
            <button type="button" className={run.watch ? "chip chip--on" : "chip"} onClick={() => run.setWatch(!run.watch)}>
              Watch
            </button>
            <button type="button" className={run.pace ? "chip chip--on" : "chip"} onClick={() => run.setPace(!run.pace)}>
              Pace
            </button>
            <button type="button" className={run.headless ? "chip chip--on" : "chip"} onClick={() => run.setHeadless(!run.headless)}>
              Headless
            </button>
            <button type="button" className={run.continuous ? "chip chip--on" : "chip"} onClick={() => run.setContinuous(!run.continuous)}>
              Continuous
            </button>
            <button type="button" className={run.dryRun ? "chip chip--on" : "chip"} onClick={() => run.setDryRun(!run.dryRun)}>
              Dry run
            </button>
          </div>
        </div>
      </section>

      <section className="panel inbox apply-workers" aria-label="Apply workers">
        <div className="panel__head">
          <div>
            <div className="panel__title">Workers</div>
            <div className="panel__sub">{workerSummary}</div>
          </div>
        </div>
        <div className="panel__body--tight">
          {run.workerSnapshots.length === 0 ? (
            <div className="p-16 text-center text-sm text-ink-3">
              {run.isRunning || run.starting
                ? "Waiting for worker heartbeats…"
                : "Start apply to see worker status."}
            </div>
          ) : (
            <div className="grid gap-8 sm:grid-cols-2">
              {run.workerSnapshots.map((worker) => (
                <div key={worker.workerId} className="worker">
                  <div className="worker__ring">
                    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
                      <circle className="worker__ring-bg" cx="14" cy="14" r="12" />
                      <circle className="worker__ring-fg" cx="14" cy="14" r="12" />
                    </svg>
                  </div>
                  <div className="worker__name">Worker {worker.workerId}</div>
                  <div className="worker__stat">
                    <span className={workerStatusbarClass(worker.status)}>
                      {workerStatusLabel(worker.status)}
                    </span>
                  </div>
                  <div className="worker__stat">{worker.detail || "—"}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="panel feed apply-logs" aria-label="Apply logs">
        <div className="panel__head">
          <div>
            <div className="panel__title">Activity</div>
            <div className="panel__sub">
              {run.isRunning ? "Live" : agent.phase === "idle" ? "Idle" : agent.label} · {run.events.length}{" "}
              events
            </div>
          </div>
        </div>
        <div className="panel__body--tight">
          <div className="scroll-thin max-h-[72vh] overflow-auto">
            <LogConsole events={run.events} errors={run.errors} />
          </div>
        </div>
      </section>
    </>
  );
}
