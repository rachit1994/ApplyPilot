import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchAgentSettings,
  fetchRun,
  fetchRunEventsHistory,
  fetchRuns,
  startRun,
  stopRun,
  subscribeRunEvents,
  type Run,
  type RunEvent,
} from "../api";
import {
  applySettingsToCliOptions,
  buildApplyCliCommand,
  type ApplyRunSettings,
} from "../utils/applyCliCommand";
import {
  deriveApplyAgentState,
  type WorkerHeartbeatInfo,
} from "../utils/applyRunState";

function isApplyRun(run: Run | null | undefined): run is Run {
  return run?.run_type === "apply";
}

async function resolveApplyRun(): Promise<Run | null> {
  const active = await fetchActiveRun();
  if (isApplyRun(active)) return active;
  const runs = await fetchRuns();
  return runs.find((r) => r.run_type === "apply") ?? null;
}

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
  const [continuous, setContinuous] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const eventsRef = useRef(events);
  const activeRunRef = useRef(activeRun);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  useEffect(() => {
    activeRunRef.current = activeRun;
  }, [activeRun]);

  const loadRunEvents = useCallback((runId: string) => {
    fetchRunEventsHistory(runId)
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
  }, []);

  useEffect(() => {
    fetchAgentSettings()
      .then((res) => {
        const score = res.agent.apply_min_score;
        if (typeof score === "number" && !Number.isNaN(score)) {
          setMinScore(Math.max(0, Math.min(10, Math.round(score))));
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    resolveApplyRun()
      .then((run) => {
        if (!run) return;
        setActiveRun(run);
        loadRunEvents(run.id);
      })
      .catch(() => {});
  }, [loadRunEvents]);

  const refreshRun = useCallback((runId: string) => {
    fetchRun(runId)
      .then(setActiveRun)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const tick = () => {
      fetchActiveRun()
        .then((run) => {
          if (isApplyRun(run)) {
            setActiveRun((prev) => {
              if (
                prev?.id === run.id &&
                prev.status === run.status &&
                prev.error_message === run.error_message &&
                prev.finished_at === run.finished_at
              ) {
                return prev;
              }
              return run;
            });
            return;
          }
          const prev = activeRunRef.current;
          if (isApplyRun(prev) && prev.status === "running") {
            refreshRun(prev.id);
          }
        })
        .catch(() => {});
    };
    const id = window.setInterval(tick, 3000);
    return () => window.clearInterval(id);
  }, [refreshRun]);

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

  const workerSnapshots: WorkerHeartbeatInfo[] = useMemo(() => {
    const latest = new Map<number, WorkerHeartbeatInfo>();
    for (const e of workerHeartbeats) {
      const payload = (e.payload ?? {}) as {
        worker_id?: number;
        status?: string;
        detail?: string;
      };
      const id = Number(payload.worker_id ?? 0);
      latest.set(id, {
        workerId: id,
        status: payload.status,
        detail: payload.detail ?? e.message ?? "",
        at: e.created_at,
      });
    }
    return [...latest.values()].sort((a, b) => a.workerId - b.workerId);
  }, [workerHeartbeats]);

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

  const agentState = useMemo(
    () => deriveApplyAgentState(activeRun, workerSnapshots, starting),
    [activeRun, workerSnapshots, starting],
  );

  const applyCli = useMemo(
    () =>
      buildApplyCliCommand(
        applySettingsToCliOptions({
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
          isRunning,
        }),
      ),
    [
      continuous,
      dryRun,
      headless,
      isRunning,
      limit,
      minScore,
      pace,
      watch,
      workers,
    ],
  );

  const applySettings: ApplyRunSettings = {
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
    isRunning,
  };

  return {
    activeRun,
    events,
    errors,
    workerHeartbeats,
    workerSnapshots,
    agentState,
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
    applyCli,
    applySettings,
  };
}
