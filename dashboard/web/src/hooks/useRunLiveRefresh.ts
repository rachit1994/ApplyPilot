import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchActiveRun, subscribeRunEvents } from "../api";

/** Invalidate stats + jobs when the active run emits pipeline progress. */
export function useRunLiveRefresh() {
  const queryClient = useQueryClient();
  const { data: activeRun } = useQuery({
    queryKey: ["runs", "active"],
    queryFn: fetchActiveRun,
    refetchInterval: 5000,
  });
  const lastEventId = useRef(0);

  useEffect(() => {
    if (!activeRun?.id || activeRun.status !== "running") return;
    const unsub = subscribeRunEvents(
      activeRun.id,
      (event) => {
        if (
          event.event_type === "stats_tick" ||
          event.event_type === "stage_progress" ||
          event.event_type === "worker_heartbeat"
        ) {
          queryClient.invalidateQueries({ queryKey: ["stats"] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          queryClient.invalidateQueries({ queryKey: ["jobs-triage-counts"] });
          queryClient.invalidateQueries({ queryKey: ["jobs-recent"] });
        }
      },
      lastEventId.current,
    );
    return unsub;
  }, [activeRun?.id, activeRun?.status, queryClient]);
}
