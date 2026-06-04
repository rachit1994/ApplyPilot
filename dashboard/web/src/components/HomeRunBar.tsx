import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStats } from "../api";
import { PIPELINE_STAGE_IDS, STAGE_LABELS, type PipelineStageId } from "../dashboardNav";
import { useHomeRuns } from "../hooks/useHomeRuns";
import { LogConsole } from "./LogConsole";
import { RunPlanModal } from "./RunPlanModal";
import { Button } from "./ui/button";

export function HomeRunBar() {
  const run = useHomeRuns();
  const [planKind, setPlanKind] = useState<"pipeline" | "apply" | null>(null);
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });

  const errors = run.events.filter((e) => e.event_type === "stage_error");

  return (
    <section className="rounded-card border border-panel-border bg-panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base text-ink">Run controls</h3>
          <p className="mt-1 text-xs text-ink-3">
            Start pipeline stages or apply from here. Jobs page is read-only triage.
          </p>
        </div>
        {run.activeRun?.status === "running" ? (
          <span className="rounded-chip bg-accent/15 px-2 py-1 text-xs font-medium text-accent">
            {run.runKind} · {run.activeRun.current_stage ?? "running"}
          </span>
        ) : null}
      </div>

      {run.error ? (
        <p role="alert" className="mt-3 text-sm text-bad">
          {run.error}
        </p>
      ) : null}

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
            Pipeline
          </p>
          <div className="flex flex-wrap gap-1.5">
            {PIPELINE_STAGE_IDS.map((stage) => (
              <button
                key={stage}
                type="button"
                disabled={run.isRunning}
                onClick={() => run.toggleStage(stage)}
                className={`rounded-chip border px-2 py-1 text-xs ${
                  run.selectedStages.includes(stage)
                    ? "border-accent/50 bg-accent/15 text-accent"
                    : "border-panel-border text-ink-3"
                }`}
              >
                {STAGE_LABELS[stage]}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-ink-3">
            <label className="flex items-center gap-1.5">
              Min score
              <input
                type="number"
                min={0}
                max={10}
                value={run.pipelineMinScore}
                disabled={run.isRunning}
                onChange={(e) => run.setPipelineMinScore(Number(e.target.value))}
                className="w-14 rounded border border-panel-border bg-canvas px-1 py-0.5"
              />
            </label>
            <label className="flex items-center gap-1.5">
              Workers
              <input
                type="number"
                min={1}
                max={8}
                value={run.workers}
                disabled={run.isRunning}
                onChange={(e) => run.setWorkers(Number(e.target.value))}
                className="w-14 rounded border border-panel-border bg-canvas px-1 py-0.5"
              />
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={run.stream}
                disabled={run.isRunning}
                onChange={(e) => run.setStream(e.target.checked)}
              />
              Stream
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={run.dryRun}
                disabled={run.isRunning}
                onChange={(e) => run.setDryRun(e.target.checked)}
              />
              Dry run
            </label>
          </div>
          <Button
            type="button"
            disabled={run.isRunning || run.starting}
            onClick={() => setPlanKind("pipeline")}
            size="sm"
          >
            Run pipeline
          </Button>
        </div>

        <div className="space-y-3">
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Apply</p>
          <div className="flex flex-wrap gap-3 text-xs text-ink-3">
            <label className="flex items-center gap-1.5">
              Limit
              <input
                type="number"
                min={1}
                placeholder="∞"
                value={run.applyLimit}
                disabled={run.isRunning}
                onChange={(e) =>
                  run.setApplyLimit(e.target.value === "" ? "" : Number(e.target.value))
                }
                className="w-16 rounded border border-panel-border bg-canvas px-1 py-0.5"
              />
            </label>
            <label className="flex items-center gap-1.5">
              Min score
              <input
                type="number"
                min={0}
                max={10}
                value={run.applyMinScore}
                disabled={run.isRunning}
                onChange={(e) => run.setApplyMinScore(Number(e.target.value))}
                className="w-14 rounded border border-panel-border bg-canvas px-1 py-0.5"
              />
            </label>
            <label className="flex items-center gap-1.5">
              Workers
              <input
                type="number"
                min={1}
                max={8}
                value={run.applyWorkers}
                disabled={run.isRunning}
                onChange={(e) => run.setApplyWorkers(Number(e.target.value))}
                className="w-14 rounded border border-panel-border bg-canvas px-1 py-0.5"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-ink-3">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={run.watch}
                disabled={run.isRunning}
                onChange={(e) => run.setWatch(e.target.checked)}
              />
              Watch
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={run.continuous}
                disabled={run.isRunning}
                onChange={(e) => run.setContinuous(e.target.checked)}
              />
              Continuous
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={run.pace}
                disabled={run.isRunning}
                onChange={(e) => run.setPace(e.target.checked)}
              />
              Pace
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={run.headless}
                disabled={run.isRunning}
                onChange={(e) => run.setHeadless(e.target.checked)}
              />
              Headless
            </label>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={run.isRunning || run.starting}
            onClick={() => setPlanKind("apply")}
            size="sm"
          >
            Run apply
          </Button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={!run.isRunning}
          onClick={() => void run.handleStop()}
        >
          Stop run
        </Button>
      </div>

      <div className="mt-4 rounded-card border border-panel-border bg-canvas p-2">
        <LogConsole events={run.events} errors={errors} />
      </div>

      <RunPlanModal
        open={planKind === "pipeline"}
        title="Start pipeline run"
        cliCommand={run.pipelineCli}
        summaryLines={[
          `Stages: ${run.selectedStages.map((s) => STAGE_LABELS[s as PipelineStageId]).join(", ")}`,
          `Min score ${run.pipelineMinScore} · ${run.workers} worker(s)`,
        ]}
        onCancel={() => setPlanKind(null)}
        onConfirm={() => {
          setPlanKind(null);
          void run.handleStartPipeline();
        }}
      />

      <RunPlanModal
        open={planKind === "apply"}
        title="Start apply run"
        cliCommand={run.applyCli}
        summaryLines={[
          `Ready: ${stats?.ready_to_apply ?? "—"} (≥${run.applyMinScore})`,
          `${run.applyWorkers} worker(s) · direct engine`,
          run.watch ? "Visible Chrome (--watch)" : run.headless ? "Headless" : "Visible Chrome",
          run.continuous ? "Drain queue (--continuous)" : "Stop when limit reached",
        ]}
        onCancel={() => setPlanKind(null)}
        onConfirm={() => {
          setPlanKind(null);
          void run.handleStartApply();
        }}
      />
    </section>
  );
}
