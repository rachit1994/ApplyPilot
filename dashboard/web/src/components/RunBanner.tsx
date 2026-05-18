import { useEffect, useState } from "react";
import type { Run } from "../api";
import { formatDuration, formatTime, runDuration } from "../utils/format";

type Props = {
  run: Run | null;
};

function statusBadgeClass(status: string): string {
  switch (status) {
    case "running":
      return "badge-running";
    case "completed":
      return "badge-completed";
    case "failed":
      return "badge-failed";
    case "stopped":
      return "badge-stopped";
    default:
      return "badge-idle";
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "stopped":
      return "Stopped";
    default:
      return status;
  }
}

export function RunBanner({ run }: Props) {
  const [, tick] = useState(0);

  useEffect(() => {
    if (run?.status !== "running") return;
    const id = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [run?.status, run?.id]);

  if (!run) {
    return (
      <section className="panel border-dashed border-zinc-700/60 px-4 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-800/80 text-zinc-500">
            <IconIdle />
          </div>
          <div>
            <p className="text-sm font-medium text-zinc-300">No active run</p>
            <p className="text-xs text-zinc-500">
              Start the pipeline below to discover, score, and tailor jobs.
            </p>
          </div>
        </div>
      </section>
    );
  }

  const durationMs = runDuration(run);
  const durationLabel = durationMs != null ? formatDuration(durationMs) : "—";
  const isRunning = run.status === "running";
  const isFailed = run.status === "failed";

  return (
    <section
      className={`panel overflow-hidden ${
        isRunning
          ? "ring-1 ring-emerald-500/30"
          : isFailed
            ? "ring-1 ring-red-500/30"
            : ""
      }`}
    >
      <div
        className={`px-4 py-4 ${
          isRunning
            ? "bg-gradient-to-r from-emerald-950/40 via-transparent to-transparent"
            : isFailed
              ? "bg-gradient-to-r from-red-950/40 via-transparent to-transparent"
              : ""
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
                isRunning
                  ? "bg-emerald-500/15 text-emerald-400"
                  : isFailed
                    ? "bg-red-500/15 text-red-400"
                    : "bg-blue-500/15 text-blue-400"
              }`}
            >
              {isRunning ? <IconSpinner /> : isFailed ? <IconError /> : <IconCheck />}
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold text-zinc-100">
                  {run.run_type === "pipeline" ? "Pipeline run" : `${run.run_type} run`}
                </h2>
                <span className={`badge ${statusBadgeClass(run.status)}`}>
                  {isRunning && (
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  )}
                  {statusLabel(run.status)}
                </span>
              </div>
              <p className="mt-0.5 font-mono text-xs text-zinc-500">{run.id}</p>
            </div>
          </div>

          <dl className="flex flex-wrap gap-4 text-xs sm:gap-6">
            <div>
              <dt className="text-zinc-500">Duration</dt>
              <dd className="mt-0.5 font-mono text-sm font-medium text-zinc-200">
                {durationLabel}
              </dd>
            </div>
            <div>
              <dt className="text-zinc-500">Started</dt>
              <dd className="mt-0.5 text-sm text-zinc-300">{formatTime(run.started_at)}</dd>
            </div>
            {run.finished_at && (
              <div>
                <dt className="text-zinc-500">Finished</dt>
                <dd className="mt-0.5 text-sm text-zinc-300">{formatTime(run.finished_at)}</dd>
              </div>
            )}
            {run.exit_code != null && (
              <div>
                <dt className="text-zinc-500">Exit code</dt>
                <dd
                  className={`mt-0.5 font-mono text-sm font-medium ${
                    run.exit_code === 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {run.exit_code}
                </dd>
              </div>
            )}
            {run.current_stage && isRunning && (
              <div>
                <dt className="text-zinc-500">Stage</dt>
                <dd className="mt-0.5 text-sm font-medium text-sky-300">{run.current_stage}</dd>
              </div>
            )}
          </dl>
        </div>

        {run.error_message && (
          <div className="mt-3 rounded-lg border border-red-900/50 bg-red-950/30 px-3 py-2 text-sm text-red-200">
            {run.error_message}
          </div>
        )}

        {run.stages.length > 0 && (
          <p className="mt-3 text-[11px] text-zinc-500">
            Stages:{" "}
            <span className="text-zinc-400">{run.stages.join(" → ")}</span>
            {run.dry_run && (
              <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-300">
                dry run
              </span>
            )}
            {run.stream && (
              <span className="ml-1 rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-300">
                stream
              </span>
            )}
          </p>
        )}
      </div>
    </section>
  );
}

function IconIdle() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
    </svg>
  );
}

function IconSpinner() {
  return (
    <svg className="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
    </svg>
  );
}

function IconError() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
    </svg>
  );
}
