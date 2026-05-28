import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Job } from "../api";
import { fetchJobs, fetchRecentJobs } from "../api";
import { jobMatchesStage, STAGE_LABELS, type PipelineStageId } from "../dashboardNav";
import { useStageRun } from "../hooks/useStageRun";
import { useDebouncedValue } from "../utils/useDebouncedValue";
import {
  latestProgressByStage,
  resolveStageProgress,
} from "../utils/stageProgress";
import { stagePendingCount } from "../utils/stageCounts";
import { LogConsole } from "./LogConsole";
import { JobsTable } from "./JobsTable";
import { RunBanner } from "./RunBanner";
import { RunPlanModal } from "./RunPlanModal";
import { TimelineRibbon } from "./pipeline/TimelineRibbon";
import { NowPanel } from "./pipeline/NowPanel";
import { DiscoverSourcePanel } from "./pipeline/DiscoverSourcePanel";
import { StageControlBar } from "./StageControlBar";
import { PhaseStepper } from "./PhaseStepper";
import { useApplyRun } from "../hooks/useApplyRun";

type Props = {
  stage: PipelineStageId;
  onJobSelect: (job: Job) => void;
};

export function StagePipelinePage({ stage, onJobSelect }: Props) {
  const run = useStageRun(stage);
  const applyRun = useApplyRun();
  const [showPlan, setShowPlan] = useState(false);
  const [minScoreFilter, setMinScoreFilter] = useState(0);
  const [jobSearch, setJobSearch] = useState("");
  const [stageJobsOnly, setStageJobsOnly] = useState(true);
  const debouncedJobSearch = useDebouncedValue(jobSearch, 300);

  const { data: jobsData, isLoading: jobsLoading } = useQuery({
    queryKey: ["jobs", minScoreFilter, "all", debouncedJobSearch],
    queryFn: () =>
      fetchJobs({
        min_score: minScoreFilter,
        pipeline_stage: "all",
        search: debouncedJobSearch.trim() || undefined,
        sort: "activity_desc",
        limit: 200,
      }),
  });

  const { data: recentJobs } = useQuery({
    queryKey: ["jobs-recent"],
    queryFn: () => fetchRecentJobs(120),
    refetchInterval: run.isRunning ? 3000 : false,
  });

  const jobs = useMemo(() => {
    const list = jobsData?.jobs ?? [];
    if (!stageJobsOnly) return list;
    return list.filter((j) => jobMatchesStage(j, stage));
  }, [jobsData?.jobs, stageJobsOnly, stage]);

  const progressByStage = useMemo(
    () => latestProgressByStage(run.allEvents),
    [run.allEvents],
  );

  const stageState = run.stageStates[stage] ?? (run.isRunning ? "active" : "pending");

  const progressSnap = useMemo(
    () =>
      resolveStageProgress(
        stage,
        stageState,
        progressByStage[stage],
        run.stats,
        run.pipelineMinScore,
      ),
    [stage, stageState, progressByStage, run.stats, run.pipelineMinScore],
  );

  const idleProgressSnap = useMemo(
    () =>
      !run.isRunning
        ? resolveStageProgress(stage, "active", undefined, run.stats, run.pipelineMinScore)
        : null,
    [run.isRunning, stage, run.stats, run.pipelineMinScore],
  );

  const runOnOtherStage =
    run.isRunning &&
    run.activeRun?.current_stage != null &&
    run.activeRun.current_stage !== stage &&
    !(run.activeRun.stages?.length === 1 && run.activeRun.stages[0] === stage);

  const pending = stagePendingCount(stage, run.stats);
  const cliPreview = useMemo(() => {
    const parts = ["applypilot", "run", stage];
    if (run.stream) parts.push("--stream");
    if (run.dryRun) parts.push("--dry-run");
    parts.push("--min-score", String(run.pipelineMinScore));
    if (run.workers > 1) parts.push("--workers", String(run.workers));
    return parts.join(" ");
  }, [stage, run.stream, run.dryRun, run.pipelineMinScore, run.workers]);

  const planSummary = useMemo(() => {
    const lines = [
      `Stage: ${STAGE_LABELS[stage]}`,
      progressSnap?.detail ?? idleProgressSnap?.detail ?? "Counts from current database snapshot",
    ];
    if (pending != null && stage !== "discover") {
      lines.push(`${pending} jobs pending at this stage`);
    }
    if (run.dryRun) lines.push("Dry run — no writes");
    return lines;
  }, [stage, progressSnap, idleProgressSnap, pending, run.dryRun]);

  return (
    <div className="space-y-4 pb-6">
      {run.error ? (
        <div
          role="alert"
          className="rounded-card border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-ink"
        >
          {run.error}
        </div>
      ) : null}

      {runOnOtherStage ? (
        <div className="rounded-card border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-ink">
          Another stage is running (
          <span className="font-mono text-warn">{run.activeRun?.current_stage}</span>). Stop it
          before starting {STAGE_LABELS[stage].toLowerCase()} here.
        </div>
      ) : null}

      <RunBanner run={run.activeRun} />

      <TimelineRibbon events={run.events} />

      <section className="rounded-card border border-panel-border bg-panel px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm text-ink">
            <span className="font-medium">Apply queue</span>
            <span className="text-ink-4"> · start auto-apply from here</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn--accent"
              disabled={applyRun.isRunning || applyRun.starting}
              onClick={() => void applyRun.handleStart()}
            >
              {applyRun.starting ? "Starting…" : "Apply queue now"}
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={!applyRun.isRunning}
              onClick={() => void applyRun.handleStop()}
            >
              Pause apply
            </button>
          </div>
        </div>
      </section>

      <StageControlBar
        stage={stage}
        isRunning={run.isRunning}
        starting={run.starting}
        stream={run.stream}
        dryRun={run.dryRun}
        minScore={run.pipelineMinScore}
        workers={run.workers}
        onMinScoreChange={run.setPipelineMinScore}
        onWorkersChange={run.setWorkers}
        onStreamChange={run.setStream}
        onDryRunChange={run.setDryRun}
        onStart={() => setShowPlan(true)}
        onStop={run.handleStop}
        activeRun={run.activeRun}
        runOnOtherStage={runOnOtherStage}
      />

      {run.isRunning ? (
        <PhaseStepper
          stageOrder={run.stageOrder}
          stageMeta={run.stageMeta}
          stageStates={run.stageStates}
          events={run.allEvents}
          stats={run.stats}
          minScore={run.pipelineMinScore}
        />
      ) : idleProgressSnap ? (
        <section className="rounded-card border border-panel-border bg-panel p-4">
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Queue snapshot</p>
          <p className="mt-2 font-mono text-sm text-ink">{idleProgressSnap.detail}</p>
          {idleProgressSnap.percent != null ? (
            <p className="mt-1 text-xs text-ink-3">{idleProgressSnap.percent}% through eligible work</p>
          ) : null}
        </section>
      ) : null}

      <NowPanel
        activeRun={run.activeRun}
        isRunning={run.isRunning}
        currentStage={run.activeRun?.current_stage ?? stage}
        stageStates={run.stageStates}
        workers={run.workers}
        progressSnap={progressSnap}
        focusStage={stage}
      />

      {stage === "discover" ? <DiscoverSourcePanel events={run.allEvents} /> : null}

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={stageJobsOnly}
            onChange={(e) => setStageJobsOnly(e.target.checked)}
            className="rounded border-panel-border"
          />
          Show only jobs at {STAGE_LABELS[stage].toLowerCase()} stage
        </label>
        <span className="font-mono tabular-nums">
          {jobs.length} shown
          {jobsData?.total != null ? ` · ${jobsData.total} total in DB` : ""}
        </span>
      </div>

      <div className="grid gap-4 pb-4 xl:grid-cols-2">
        <LogConsole events={run.events} errors={run.errors} />
        <JobsTable
          jobs={jobs}
          recentJobs={recentJobs ?? []}
          minScoreFilter={minScoreFilter}
          onMinScoreChange={setMinScoreFilter}
          pipelineStageFilter="all"
          onPipelineStageChange={() => {}}
          search={jobSearch}
          onSearchChange={setJobSearch}
          total={jobs.length}
          isLoading={jobsLoading}
          onJobSelect={onJobSelect}
        />
      </div>

      <RunPlanModal
        open={showPlan}
        title={`Start ${STAGE_LABELS[stage]}`}
        cliCommand={cliPreview}
        summaryLines={planSummary}
        onCancel={() => setShowPlan(false)}
        onConfirm={() => {
          setShowPlan(false);
          void run.handleStart();
        }}
      />
    </div>
  );
}
