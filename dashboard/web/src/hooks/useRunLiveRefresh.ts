import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Run } from "../api";
import { subscribeRunEvents } from "../api";
import { createInvalidateThrottle } from "../utils/queryInvalidateThrottle";

const LIVE_INVALIDATE_MS = 4000;

/** Invalidate stats + jobs when the active run emits pipeline progress. */
export function useRunLiveRefresh(activeRun: Run | null | undefined) {
  const queryClient = useQueryClient();
  const lastEventId = useRef(0);
  const throttleRef = useRef(createInvalidateThrottle(LIVE_INVALIDATE_MS));

  useEffect(() => {
    throttleRef.current = createInvalidateThrottle(LIVE_INVALIDATE_MS);
  }, [activeRun?.id]);

  useEffect(() => {
    if (!activeRun?.id || activeRun.status !== "running") return;
    const invalidateLive = throttleRef.current;
    const unsub = subscribeRunEvents(
      activeRun.id,
      (event) => {
        if (
          event.event_type === "stats_tick" ||
          event.event_type === "stage_progress" ||
          event.event_type === "worker_heartbeat"
        ) {
          invalidateLive(() => {
            void queryClient.invalidateQueries({ queryKey: ["stats"] });
            void queryClient.invalidateQueries({ queryKey: ["jobs"] });
            void queryClient.invalidateQueries({ queryKey: ["jobs-triage-counts"] });
            void queryClient.invalidateQueries({ queryKey: ["jobs-recent"] });
          });
        }
      },
      lastEventId.current,
    );
    return unsub;
  }, [activeRun?.id, activeRun?.status, queryClient]);
}
