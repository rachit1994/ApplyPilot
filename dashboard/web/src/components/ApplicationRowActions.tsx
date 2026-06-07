import type { MouseEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Application } from "../api";
import { fetchRequeueApplication, fetchRetryApplication } from "../api";
import { canRequeueApply, canRetryUnverifiedApply } from "../utils/applicationAudit";

export type ApplyListAction = "requeue" | "retry";

export type ApplyListActionInfo = {
  action: ApplyListAction;
  url: string;
  title: string | null;
};

type Props = {
  app: Application;
  layout?: "row" | "inline" | "links";
  onApplyListAction?: (info: ApplyListActionInfo) => void;
};

function invalidateApplyLists(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["applications"] });
  void queryClient.invalidateQueries({ queryKey: ["stats"] });
  void queryClient.invalidateQueries({ queryKey: ["overview"] });
  void queryClient.invalidateQueries({ queryKey: ["jobs"] });
}

export function ApplicationRowActions({ app, layout = "row", onApplyListAction }: Props) {
  const queryClient = useQueryClient();
  const showRetry = canRetryUnverifiedApply(app);
  const showRequeue = canRequeueApply(app) && !showRetry;

  const requeueMut = useMutation({
    mutationFn: () => fetchRequeueApplication(app.url),
    onSuccess: () => {
      invalidateApplyLists(queryClient);
      onApplyListAction?.({ action: "requeue", url: app.url, title: app.title });
    },
  });

  const retryMut = useMutation({
    mutationFn: () => fetchRetryApplication(app.url),
    onSuccess: () => {
      invalidateApplyLists(queryClient);
      onApplyListAction?.({ action: "retry", url: app.url, title: app.title });
    },
  });

  if (!showRequeue && !showRetry) return null;

  const busy = requeueMut.isPending || retryMut.isPending;
  const err =
    (requeueMut.error instanceof Error ? requeueMut.error.message : null) ||
    (retryMut.error instanceof Error ? retryMut.error.message : null);

  const stopRowClick = (e: MouseEvent) => {
    e.stopPropagation();
  };

  const className =
    layout === "row"
      ? "app-row__actions"
      : layout === "links"
        ? "app-detail__links-actions"
        : "app-detail__toolbar-group";

  return (
    <div className={className} onClick={stopRowClick} onKeyDown={(e) => e.stopPropagation()}>
      {showRetry ? (
        <button
          type="button"
          className="btn btn--sm"
          disabled={busy}
          title="Clear unverified state and try applying again"
          onClick={() => retryMut.mutate()}
        >
          {retryMut.isPending ? "…" : "Retry"}
        </button>
      ) : null}
      {showRequeue ? (
        <button
          type="button"
          className="btn btn--sm btn--accent"
          disabled={busy}
          title="Reset this job for the apply queue (run applypilot apply to process)"
          onClick={() => requeueMut.mutate()}
        >
          {requeueMut.isPending ? "…" : "Re-apply"}
        </button>
      ) : null}
      {err ? (
        <span className="app-row__action-err" title={err}>
          Failed
        </span>
      ) : null}
    </div>
  );
}
