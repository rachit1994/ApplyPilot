import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchRun,
  fetchRunEventsHistory,
  startRun,
  stopRun,
  subscribeRunEvents,
  type Run,
  type RunEvent,
} from "../api";

export function useApplyRun() {
  const queryClient = useQueryClient();
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [limit, setLimit] = useState<number | "">("");
  const [minScore, setMinScore] = useState(7);
  const [workers, setWorkers] = useState(1);
  const [watch, setWatch] = useState(true);
  const [pace, setPace] = useState(false);
  const [headless, setHeadless] = useState(false);
  const [continuous, setContinuous] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const eventsRef = useRef(events);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  useEffect(() => {
    fetchActiveRun()
      .then((run) => {
        if (!run || run.run_type !== "apply") return;
        setActiveRun(run);
        if (run.status !== "running") {
          fetchRunEventsHistory(run.id).then(setEvents).catch(() => {});
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
        if (
          event.event_type === "stats_tick" ||
          event.event_type === "worker_heartbeat"
        ) {
          queryClient.invalidateQueries({ queryKey: ["stats"] });
          queryClient.invalidateQueries({ queryKey: ["applications"] });
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

  const handleStart = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      const run = await startRun({
        run_type: "apply",
        min_score: minScore,
        workers,
        watch,
        pace,
        headless,
        continuous,
        dry_run: dryRun,
        limit: limit === "" ? undefined : Number(limit),
      });
      setActiveRun(run);
      setEvents([]);
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start apply");
    } finally {
      setStarting(false);
    }
  }, [
    continuous,
    dryRun,
    headless,
    limit,
    minScore,
    pace,
    queryClient,
    watch,
    workers,
  ]);

  const handleStop = useCallback(async () => {
    if (!activeRun?.id) return;
    setError(null);
    try {
      const run = await stopRun(activeRun.id);
      setActiveRun(run);
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop");
    }
  }, [activeRun?.id, queryClient]);

  const workerHeartbeats = events.filter((e) => e.event_type === "worker_heartbeat");

  const errors = useMemo(
    () =>
      events.filter(
        (e) =>
          e.event_type === "stage_error" ||
          e.level === "ERROR" ||
          e.level === "error",
      ),
    [events],
  );

  return {
    activeRun,
    events,
    errors,
    workerHeartbeats,
    isRunning,
    starting,
    error,
    limit,
    setLimit,
    minScore,
    setMinScore,
    workers,
    setWorkers,
    watch,
    setWatch,
    pace,
    setPace,
    headless,
    setHeadless,
    continuous,
    setContinuous,
    dryRun,
    setDryRun,
    handleStart,
    handleStop,
  };
}
