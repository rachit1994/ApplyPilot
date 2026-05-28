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
  const [continuous, setContinuous] = useState(false);
  const [applyDryRun, setApplyDryRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [pipelineStartRequested, setPipelineStartRequested] = useState(false);
  const eventsRef = useRef(events);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  const { data: stagesMeta } = useQuery({
    queryKey: ["stages"],
    queryFn: fetchStages,
  });

  const stageOrder = stagesMeta?.order ?? [...PIPELINE_STAGE_IDS];

  useEffect(() => {
    fetchActiveRun()
      .then((run) => {
        if (!run) return;
        setActiveRun(run);
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
  }, []);

  useEffect(() => {
    const tick = () => {
      fetchActiveRun()
        .then((run) => {
          setActiveRun((prev) => {
            if (!run) {
              return prev?.status === "running" ? null : prev;
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
        })
        .catch(() => {});
    };
    const id = window.setInterval(tick, 3000);
    return () => window.clearInterval(id);
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
          event.event_type === "stage_progress" ||
          event.event_type === "worker_heartbeat"
        ) {
          queryClient.invalidateQueries({ queryKey: ["stats"] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
        }
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

  const toggleStage = useCallback((stage: PipelineStageId) => {
    setSelectedStages((prev) => {
      if (prev.includes(stage)) {
        return prev.filter((s) => s !== stage);
      }
      return [...prev, stage];
    });
  }, []);

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
      const run = await startRun({
        run_type: "pipeline",
        stages: selectedStages,
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

  const pipelineCli = useMemo(() => {
    const parts = ["applypilot", "run", ...selectedStages];
    parts.push("--min-score", String(pipelineMinScore));
    parts.push("--workers", String(workers));
    if (stream) parts.push("--stream");
    if (dryRun) parts.push("--dry-run");
    return parts.join(" ");
  }, [selectedStages, pipelineMinScore, workers, stream, dryRun]);

  const applyCli = useMemo(() => {
    const parts = ["applypilot", "apply"];
    if (applyLimit !== "") parts.push("--limit", String(applyLimit));
    parts.push("--min-score", String(applyMinScore));
    parts.push("--workers", String(applyWorkers));
    if (watch) parts.push("--watch");
    if (pace) parts.push("--pace");
    if (headless) parts.push("--headless");
    if (continuous) parts.push("--continuous");
    if (applyDryRun) parts.push("--dry-run");
    return parts.join(" ");
  }, [applyLimit, applyMinScore, applyWorkers, watch, pace, headless, continuous, applyDryRun]);

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
