import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchRun,
  fetchRunEventsHistory,
  fetchStages,
  fetchStats,
  startRun,
  stopRun,
  subscribeRunEvents,
  type Run,
  type RunEvent,
} from "../api";
import type { PipelineStageId } from "../dashboardNav";
import { filterEventsForStage } from "../dashboardNav";

export function useStageRun(stage: PipelineStageId) {
  const queryClient = useQueryClient();
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [stream, setStream] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [pipelineMinScore, setPipelineMinScore] = useState(7);
  const [workers, setWorkers] = useState(1);
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

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

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
        if (event.event_type === "stats_tick" || event.event_type === "stage_progress") {
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

  const stageEvents = useMemo(
    () => filterEventsForStage(events, stage),
    [events, stage],
  );

  const errors = useMemo(
    () => stageEvents.filter((e) => e.event_type === "stage_error"),
    [stageEvents],
  );

  const handleStart = useCallback(async () => {
    setError(null);
    setStarting(true);
    setEvents([]);
    try {
      const run = await startRun({
        run_type: "pipeline",
        stages: [stage],
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
  }, [stage, stream, dryRun, pipelineMinScore, workers, queryClient]);

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

  return {
    activeRun,
    events: stageEvents,
    allEvents: events,
    errors,
    stats,
    statsLoading,
    stageOrder,
    stageMeta: stagesMeta?.meta ?? {},
    stageStates,
    stream,
    setStream,
    dryRun,
    setDryRun,
    pipelineMinScore,
    setPipelineMinScore,
    workers,
    setWorkers,
    error,
    starting,
    isRunning,
    handleStart,
    handleStop,
  };
}
