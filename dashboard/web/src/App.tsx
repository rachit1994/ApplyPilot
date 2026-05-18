import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchRun,
  fetchRunEventsHistory,
  fetchJobs,
  fetchRecentJobs,
  fetchStages,
  fetchStats,
  startRun,
  stopRun,
  subscribeRunEvents,
  type Run,
  type RunEvent,
} from "./api";
import { ControlBar } from "./components/ControlBar";
import { PhaseStepper } from "./components/PhaseStepper";
import { LogConsole } from "./components/LogConsole";
import { StatsRow } from "./components/StatsRow";
import { JobsTable } from "./components/JobsTable";
import { RunHistory } from "./components/RunHistory";
import { RunBanner } from "./components/RunBanner";
import { ConnectionStatus } from "./components/ConnectionStatus";

export default function App() {
  const queryClient = useQueryClient();
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [selectedStages, setSelectedStages] = useState<string[]>([]);
  const [runType, setRunType] = useState("pipeline");
  const [stream, setStream] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [pipelineMinScore, setPipelineMinScore] = useState(7);
  const [workers, setWorkers] = useState(1);
  const [minScoreFilter, setMinScoreFilter] = useState(5);
  const [jobSearch, setJobSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const eventsRef = useRef(events);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  const { data: stagesMeta } = useQuery({
    queryKey: ["stages"],
    queryFn: fetchStages,
  });

  const stageOrder = stagesMeta?.order ?? [];

  useEffect(() => {
    if (stageOrder.length && selectedStages.length === 0) {
      setSelectedStages(stageOrder);
    }
  }, [stageOrder, selectedStages.length]);

  const {
    data: stats,
    isLoading: statsLoading,
  } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const {
    data: jobsData,
    isLoading: jobsLoading,
  } = useQuery({
    queryKey: ["jobs", minScoreFilter, jobSearch],
    queryFn: () =>
      fetchJobs({
        min_score: minScoreFilter,
        search: jobSearch.trim() || undefined,
        limit: 150,
      }),
  });

  const { data: recentJobs } = useQuery({
    queryKey: ["jobs-recent"],
    queryFn: () => fetchRecentJobs(120),
    refetchInterval: activeRun?.status === "running" ? 3000 : false,
  });

  const loadRunDetail = useCallback(async (runId: string, status: string) => {
    const run = await fetchRun(runId);
    setActiveRun(run);
    if (status === "running") {
      return;
    }
    const history = await fetchRunEventsHistory(runId);
    setEvents(history);
  }, []);

  useEffect(() => {
    fetchActiveRun()
      .then((run) => {
        if (!run) return;
        setActiveRun(run);
        if (run.status !== "running") {
          fetchRunEventsHistory(run.id)
            .then(setEvents)
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, []);

  const refreshRun = useCallback((runId: string) => {
    fetchRun(runId)
      .then(setActiveRun)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!activeRun?.id || activeRun.status !== "running") return;
    const lastId = eventsRef.current.reduce((m, e) => Math.max(m, e.id ?? 0), 0);
    const unsub = subscribeRunEvents(
      activeRun.id,
      (event) => {
        setEvents((prev) => {
          const next = [...prev, event];
          if (next.length > 2000) return next.slice(-1500);
          return next;
        });
        if (event.event_type === "stats_tick") {
          queryClient.invalidateQueries({ queryKey: ["stats"] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          queryClient.invalidateQueries({ queryKey: ["jobs-recent"] });
        }
        if (event.event_type === "run_finished") {
          const runId = event.run_id;
          if (runId) refreshRun(runId);
          queryClient.invalidateQueries({ queryKey: ["stats"] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          queryClient.invalidateQueries({ queryKey: ["jobs-recent"] });
          queryClient.invalidateQueries({ queryKey: ["runs"] });
        }
      },
      lastId,
    );
    return unsub;
  }, [activeRun?.id, activeRun?.status, queryClient, refreshRun]);

  useEffect(() => {
    if (!activeRun?.id || activeRun.status !== "running") return;
    const timer = window.setInterval(() => refreshRun(activeRun.id), 4000);
    return () => window.clearInterval(timer);
  }, [activeRun?.id, activeRun?.status, refreshRun]);

  const handleSelectHistoryRun = useCallback(
    async (run: Run) => {
      setError(null);
      setEvents([]);
      try {
        await loadRunDetail(run.id, run.status);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load run");
      }
    },
    [loadRunDetail],
  );

  const stageStates = useMemo(() => {
    const states: Record<string, "pending" | "active" | "done" | "error"> = {};
    for (const s of stageOrder) states[s] = "pending";
    if (activeRun?.current_stage) {
      for (const s of stageOrder) {
        if (s === activeRun.current_stage) states[s] = "active";
      }
    }
    for (const e of events) {
      if (e.event_type === "stage_end" && e.stage) states[e.stage] = "done";
      if (e.event_type === "stage_start" && e.stage) states[e.stage] = "active";
      if (e.event_type === "stage_error" && e.stage) states[e.stage] = "error";
    }
    return states;
  }, [stageOrder, activeRun?.current_stage, events]);

  const errors = useMemo(
    () =>
      events.filter(
        (e) => e.level === "error" || e.event_type === "stage_error",
      ),
    [events],
  );

  const handleStart = useCallback(async () => {
    setError(null);
    setStarting(true);
    setEvents([]);
    try {
      const run = await startRun({
        run_type: runType,
        stages: selectedStages.length === stageOrder.length ? null : selectedStages,
        stream,
        dry_run: dryRun,
        min_score: pipelineMinScore,
        workers,
      });
      setActiveRun(run);
      if (run.status === "failed" || run.status === "stopped") {
        setError(run.error_message ?? `Run ended with status: ${run.status}`);
        if (run.id) {
          fetchRunEventsHistory(run.id)
            .then(setEvents)
            .catch(() => {});
        }
      }
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed");
    } finally {
      setStarting(false);
    }
  }, [
    selectedStages,
    stageOrder.length,
    stream,
    dryRun,
    runType,
    pipelineMinScore,
    workers,
    queryClient,
  ]);

  const handleStop = useCallback(async () => {
    if (!activeRun?.id) return;
    setError(null);
    try {
      const run = await stopRun(activeRun.id);
      setActiveRun(run);
      refreshRun(run.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stop failed");
    }
  }, [activeRun?.id, refreshRun]);

  const isRunning = activeRun?.status === "running";
  const displayStages = selectedStages.length ? selectedStages : stageOrder;

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/80">
        <div className="border-b border-zinc-800/80 px-4 py-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 text-xs font-bold text-white shadow-lg shadow-blue-500/20">
              AP
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-zinc-100">
                ApplyPilot
              </h1>
              <p className="text-[10px] text-zinc-500">Control panel</p>
            </div>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-3 overflow-hidden p-3">
          <ConnectionStatus />
          <RunHistory
            activeRunId={activeRun?.id ?? null}
            onSelectRun={handleSelectHistoryRun}
          />
        </div>

        <footer className="border-t border-zinc-800/80 px-4 py-3 text-[10px] text-zinc-600">
          Local-first · ~/.applypilot
        </footer>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-zinc-800/80 bg-zinc-950/50 px-6 py-4 backdrop-blur-sm">
          <h2 className="text-lg font-semibold text-zinc-100">Pipeline dashboard</h2>
          <p className="mt-0.5 text-sm text-zinc-500">
            Discover, score, and tailor jobs — watch each stage live.
          </p>
        </header>

        <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-6">
          <div className="scroll-thin max-h-[26vh] shrink-0 space-y-4 overflow-y-auto">
            {error && (
            <div
              role="alert"
              className="rounded-lg border border-red-800/60 bg-red-950/40 px-4 py-3 text-sm text-red-200"
            >
              {error}
            </div>
          )}

          <RunBanner run={activeRun} />

          <ControlBar
            isRunning={isRunning}
            starting={starting}
            runType={runType}
            onRunTypeChange={setRunType}
            stream={stream}
            dryRun={dryRun}
            minScore={pipelineMinScore}
            workers={workers}
            onMinScoreChange={setPipelineMinScore}
            onWorkersChange={setWorkers}
            stageOrder={stageOrder}
            selectedStages={selectedStages}
            onToggleStage={(stage) =>
              setSelectedStages((prev) =>
                prev.includes(stage) ? prev.filter((s) => s !== stage) : [...prev, stage],
              )
            }
            onSelectAll={() => setSelectedStages(stageOrder)}
            onStreamChange={setStream}
            onDryRunChange={setDryRun}
            onStart={handleStart}
            onStop={handleStop}
            activeRun={activeRun}
          />

            <StatsRow stats={stats} isLoading={statsLoading} />

            <PhaseStepper
              stageOrder={displayStages}
              stageMeta={stagesMeta?.meta ?? {}}
              stageStates={stageStates}
              events={events}
            />
          </div>

          <div className="grid min-h-[58vh] flex-1 gap-4 overflow-hidden xl:grid-cols-2">
            <LogConsole events={events} errors={errors} />
            <JobsTable
              jobs={jobsData?.jobs ?? []}
              recentJobs={recentJobs ?? []}
              minScoreFilter={minScoreFilter}
              onMinScoreChange={setMinScoreFilter}
              search={jobSearch}
              onSearchChange={setJobSearch}
              total={jobsData?.total ?? 0}
              isLoading={jobsLoading}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
