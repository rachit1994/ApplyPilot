import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Application, ApplicationDetail } from "../api";
import {
  fetchApplicationDetail,
  fetchConfirmApplication,
  fetchMarkApplicationApplied,
  fetchRequeueApplication,
  fetchRetryApplication,
} from "../api";

type Props = {
  app: Application;
  expanded: boolean;
  onToggle: () => void;
  onOpenDrawer?: () => void;
};

export function ApplicationRow({ app, expanded, onToggle, onOpenDrawer }: Props) {
  const queryClient = useQueryClient();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const confirmMut = useMutation({
    mutationFn: () => fetchConfirmApplication(app.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const retryMut = useMutation({
    mutationFn: () => fetchRetryApplication(app.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const markAppliedMut = useMutation({
    mutationFn: () => fetchMarkApplicationApplied(app.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const requeueMut = useMutation({
    mutationFn: () => fetchRequeueApplication(app.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const loadDetail = async () => {
    if (detail) return;
    setDetailError(null);
    try {
      const d = await fetchApplicationDetail(app.url);
      setDetail(d);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Failed to load detail");
    }
  };

  const handleToggle = () => {
    if (!expanded) void loadDetail();
    onToggle();
  };

  const status = app.apply_status ?? "unknown";
  const isUnverified = status === "submitted_unverified";
  const canMarkApplied = status === "manual" || status === "failed";
  const canRequeue = status === "manual" || status === "failed";

  return (
    <article className="rounded-card border border-panel-border bg-panel">
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-panel-elevated"
      >
        <StatusChip status={status} />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">{app.title ?? "Untitled"}</p>
          <p className="mt-0.5 text-xs text-ink-3">
            {app.site ?? "—"}
            {app.fit_score != null ? ` · fit ${app.fit_score}` : null}
            {app.applied_at ? ` · ${formatWhen(app.applied_at)}` : null}
          </p>
          {app.apply_error ? (
            <p className="mt-1 line-clamp-2 text-xs text-warn">{app.apply_error}</p>
          ) : null}
        </div>
        <span className="text-xs text-ink-4">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded ? (
        <div className="border-t border-panel-border px-4 py-3 text-sm">
          <div className="flex flex-wrap gap-2">
            {app.application_url ? (
              <a
                href={app.application_url}
                target="_blank"
                rel="noreferrer"
                className="rounded-btn border border-panel-border px-3 py-1 text-xs text-accent hover:bg-panel-elevated"
              >
                Open application
              </a>
            ) : null}
            <a
              href={app.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-btn border border-panel-border px-3 py-1 text-xs text-ink-2 hover:bg-panel-elevated"
            >
              Job URL
            </a>
            {onOpenDrawer ? (
              <button
                type="button"
                onClick={onOpenDrawer}
                className="rounded-btn border border-accent/40 px-3 py-1 text-xs text-accent hover:bg-accent/10"
              >
                Audit drawer
              </button>
            ) : null}
            {isUnverified ? (
              <>
                <button
                  type="button"
                  disabled={confirmMut.isPending}
                  onClick={() => confirmMut.mutate()}
                  className="rounded-btn bg-good/15 px-3 py-1 text-xs text-good hover:bg-good/25 disabled:opacity-50"
                >
                  Confirm applied
                </button>
                <button
                  type="button"
                  disabled={retryMut.isPending}
                  onClick={() => retryMut.mutate()}
                  className="rounded-btn bg-warn/15 px-3 py-1 text-xs text-warn hover:bg-warn/25 disabled:opacity-50"
                >
                  Retry apply
                </button>
              </>
            ) : null}
            {canMarkApplied ? (
              <button
                type="button"
                disabled={markAppliedMut.isPending}
                onClick={() => markAppliedMut.mutate()}
                className="rounded-btn bg-good/15 px-3 py-1 text-xs text-good hover:bg-good/25 disabled:opacity-50"
              >
                Mark applied
              </button>
            ) : null}
            {canRequeue ? (
              <button
                type="button"
                disabled={requeueMut.isPending}
                onClick={() => requeueMut.mutate()}
                className="rounded-btn bg-warn/15 px-3 py-1 text-xs text-warn hover:bg-warn/25 disabled:opacity-50"
              >
                Re-queue
              </button>
            ) : null}
          </div>

          {detailError ? <p className="mt-3 text-xs text-bad">{detailError}</p> : null}

          {detail?.log_detail?.parsed?.fields?.length ? (
            <div className="mt-3">
              <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
                Form snapshot
              </p>
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto font-mono text-xs">
                {detail.log_detail.parsed.fields.map((f) => (
                  <li key={f.label} className="flex justify-between gap-2 text-ink-2">
                    <span className="text-ink-4">{f.label}</span>
                    <span className={f.empty ? "text-warn" : ""}>{f.value || "—"}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {detail?.log_detail?.log_excerpt ? (
            <pre className="mt-3 max-h-40 overflow-auto rounded border border-panel-border bg-canvas p-2 font-mono text-[10px] text-ink-3">
              {detail.log_detail.log_excerpt}
            </pre>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function StatusChip({ status }: { status: string }) {
  const tone =
    status === "applied"
      ? "bg-good/15 text-good"
      : status === "submitted_unverified"
        ? "bg-warn/15 text-warn"
        : status === "failed"
          ? "bg-bad/15 text-bad"
          : "bg-panel-elevated text-ink-3";
  return (
    <span className={`shrink-0 rounded-chip px-2 py-0.5 text-[10px] font-medium uppercase ${tone}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
