import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchRun,
  fetchRunEventsHistory,
  fetchStages,
  startRun,
  stopRun,
  subscribeRunEvents,
  type Run,
  type RunEvent,
} from "../api";
import { PIPELINE_STAGE_IDS, type PipelineStageId } from "../dashboardNav";
import {
  applySettingsToCliOptions,
  buildApplyCliCommand,
} from "../utils/applyCliCommand";
import {
  buildPipelineCliCommand,
  orderedPipelineStages,
} from "../utils/pipelineRunPlan";

export function useHomeRuns() {
  const queryClient = useQueryClient();
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [selectedStages, setSelectedStages] = useState<PipelineStageId[]>([
    ...PIPELINE_STAGE_IDS,
  ]);
  const [stream, setStream] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [pipelineMinScore, setPipelineMinScore] = useState(7);
  const [workers, setWorkers] = useState(1);
  const [applyLimit, setApplyLimit] = useState<number | "">("");
  const [applyMinScore, setApplyMinScore] = useState(7);
  const [applyWorkers, setApplyWorkers] = useState(1);
  const [watch, setWatch] = useState(true);
  const [pace, setPace] = useState(false);
  const [headless, setHeadless] = useState(false);
  const [continuous, setContinuous] = useState(true);
  const [applyDryRun, setApplyDryRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [pipelineStartRequested, setPipelineStartRequested] = useState(false);
  const eventsRef = useRef(events);
  const activeRunSigRef = useRef("");

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  const syncActiveRunPoll = useCallback(
    (run: Run | null) => {
      const sig = run
        ? `${run.id}:${run.status}:${run.current_stage ?? ""}`
        : "";
      if (sig !== activeRunSigRef.current) {
        activeRunSigRef.current = sig;
        if (run) {
          queryClient.invalidateQueries({ queryKey: ["overview"] });
          queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
        }
      }
      setActiveRun((prev) => {
        if (!run) {
          if (prev?.status === "running" && prev.id) {
            fetchRun(prev.id)
              .then((fresh) => {
                if (fresh.status !== "running") {
                  activeRunSigRef.current = `${fresh.id}:${fresh.status}:${fresh.current_stage ?? ""}`;
                  setActiveRun(fresh);
                  queryClient.invalidateQueries({ queryKey: ["overview"] });
                  queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
                }
              })
              .catch(() => {});
            return prev;
          }
          return null;
        }
        if (
          prev?.id === run.id &&
          prev.status === run.status &&
          prev.current_stage === run.current_stage
        ) {
          return prev;
        }
        return run;
      });
    },
    [queryClient],
  );

  const { data: stagesMeta } = useQuery({
    queryKey: ["stages"],
    queryFn: fetchStages,
    refetchInterval: false,
    staleTime: 60_000,
  });

  const stageOrder = stagesMeta?.order ?? [...PIPELINE_STAGE_IDS];

  useEffect(() => {
    fetchActiveRun()
      .then((run) => {
        syncActiveRunPoll(run);
        if (!run) return;
        fetchRunEventsHistory(run.id)
          .then((history) => {
            setEvents((prev) => {
              if (prev.length === 0) return history;
              const seen = new Set(prev.map((e) => e.id));
              const merged = [...prev];
              for (const e of history) {
                if (e.id != null && seen.has(e.id)) continue;
                merged.push(e);
              }
              merged.sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
              return merged.length > 2000 ? merged.slice(-1500) : merged;
            });
          })
          .catch(() => {});
      })
      .catch(() => {});
  }, [syncActiveRunPoll]);

  useEffect(() => {
    const tick = () => {
      fetchActiveRun()
        .then(syncActiveRunPoll)
        .catch(() => {});
    };
    const id = window.setInterval(tick, 10_000);
    return () => window.clearInterval(id);
  }, [syncActiveRunPoll]);

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
        if (event.event_type === "log" || event.event_type === "stage_error") {
          queryClient.invalidateQueries({ queryKey: ["overview"] });
        }
        if (event.event_type === "run_finished") {
          refreshRun(activeRun.id);
          queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
        }
      },
      lastId,
    );
    return unsub;
  }, [activeRun?.id, activeRun?.status, queryClient, refreshRun]);

  const isRunning = activeRun?.status === "running";
  const runKind = activeRun?.run_type ?? null;

  useEffect(() => {
    if (!pipelineStartRequested) return;
    if (activeRun?.run_type === "pipeline" && activeRun.status === "running") {
      setPipelineStartRequested(false);
    }
  }, [activeRun?.run_type, activeRun?.status, pipelineStartRequested]);

  const toggleStage = useCallback(
    (stage: PipelineStageId) => {
      setSelectedStages((prev) => {
        const next = prev.includes(stage)
          ? prev.filter((s) => s !== stage)
          : [...prev, stage];
        return orderedPipelineStages(next, stageOrder);
      });
    },
    [stageOrder],
  );

  const setSelectedStagesOrdered = useCallback(
    (stages: PipelineStageId[]) => {
      setSelectedStages(orderedPipelineStages(stages, stageOrder));
    },
    [stageOrder],
  );

  const handleStartPipeline = useCallback(async () => {
    if (selectedStages.length === 0) {
      setError("Select at least one pipeline stage.");
      return;
    }
    setError(null);
    setPipelineStartRequested(true);
    setStarting(true);
    setEvents([]);
    try {
      const stages = orderedPipelineStages(selectedStages, stageOrder);
      const run = await startRun({
        run_type: "pipeline",
        stages,
        stream,
        dry_run: dryRun,
        min_score: pipelineMinScore,
        workers,
      });
      setActiveRun(run);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline start failed");
      setPipelineStartRequested(false);
    } finally {
      setStarting(false);
    }
  }, [
    selectedStages,
    stageOrder,
    stream,
    dryRun,
    pipelineMinScore,
    workers,
    queryClient,
  ]);

  const handleStartApply = useCallback(async () => {
    setError(null);
    setStarting(true);
    setEvents([]);
    try {
      const run = await startRun({
        run_type: "apply",
        min_score: applyMinScore,
        workers: applyWorkers,
        limit: applyLimit === "" ? undefined : applyLimit,
        watch,
        pace,
        headless,
        continuous,
        dry_run: applyDryRun,
      });
      setActiveRun(run);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Apply start failed");
    } finally {
      setStarting(false);
    }
  }, [
    applyLimit,
    applyMinScore,
    applyWorkers,
    watch,
    pace,
    headless,
    continuous,
    applyDryRun,
    queryClient,
  ]);

  const handleStop = useCallback(async () => {
    if (!activeRun?.id) return;
    setError(null);
    try {
      const run = await stopRun(activeRun.id);
      setActiveRun(run);
      refreshRun(run.id);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stop failed");
    }
  }, [activeRun?.id, queryClient, refreshRun]);

  const pipelineCli = useMemo(
    () =>
      buildPipelineCliCommand({
        selectedStages,
        stageOrder,
        minScore: pipelineMinScore,
        workers,
        stream,
        dryRun,
      }),
    [selectedStages, stageOrder, pipelineMinScore, workers, stream, dryRun],
  );

  const applyCli = useMemo(
    () =>
      buildApplyCliCommand(
        applySettingsToCliOptions({
          limit: applyLimit,
          setLimit: setApplyLimit,
          minScore: applyMinScore,
          setMinScore: setApplyMinScore,
          workers: applyWorkers,
          setWorkers: setApplyWorkers,
          watch,
          setWatch,
          pace,
          setPace,
          headless,
          setHeadless,
          continuous,
          setContinuous,
          dryRun: applyDryRun,
          setDryRun: setApplyDryRun,
          isRunning,
        }),
      ),
    [
      applyDryRun,
      applyLimit,
      applyMinScore,
      applyWorkers,
      continuous,
      headless,
      isRunning,
      pace,
      watch,
    ],
  );

  return {
    activeRun,
    events,
    isRunning,
    runKind,
    error,
    starting,
    pipelineStartRequested,
    stageOrder,
    selectedStages,
    setSelectedStages: setSelectedStagesOrdered,
    toggleStage,
    stream,
    setStream,
    dryRun,
    setDryRun,
    pipelineMinScore,
    setPipelineMinScore,
    workers,
    setWorkers,
    applyLimit,
    setApplyLimit,
    applyMinScore,
    setApplyMinScore,
    applyWorkers,
    setApplyWorkers,
    watch,
    setWatch,
    pace,
    setPace,
    headless,
    setHeadless,
    continuous,
    setContinuous,
    applyDryRun,
    setApplyDryRun,
    handleStartPipeline,
    handleStartApply,
    handleStop,
    pipelineCli,
    applyCli,
  };
}
