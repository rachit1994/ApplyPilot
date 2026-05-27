import { useEffect, useState } from "react";
import type { Application, ApplicationDetail, Job } from "../../api";
import {
  fetchApplicationDetail,
  fetchConfirmApplication,
  fetchRetryApplication,
} from "../../api";

type Props = {
  job: Job | null;
  application: Application | null;
  onClose: () => void;
};

export function RightDrawer({ job, application, onClose }: Props) {
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);

  useEffect(() => {
    if (!application?.url) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    fetchApplicationDetail(application.url)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [application?.url]);

  if (!job && !application) return null;

  const title = job?.title ?? application?.title ?? "Untitled";
  const isUnverified = application?.apply_status === "submitted_unverified";

  return (
    <aside
      className="flex w-96 shrink-0 flex-col border-l border-panel-border bg-panel"
      aria-label="Details"
    >
      <header className="flex items-start justify-between gap-2 border-b border-panel-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
            {application ? "Application" : "Job"}
          </p>
          <h2 className="mt-1 text-sm font-medium text-balance text-ink">{title}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-[var(--rad-btn)] px-2 py-1 text-xs text-ink-3 hover:bg-panel-elevated hover:text-ink"
          aria-label="Close details"
        >
          Close
        </button>
      </header>

      <div className="scroll-thin flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        {job ? <JobAudit job={job} /> : null}
        {application ? (
          <ApplicationAudit application={application} detail={detail} isUnverified={isUnverified} />
        ) : null}
      </div>
    </aside>
  );
}

function JobAudit({ job }: { job: Job }) {
  return (
    <>
      <DetailRow label="Fit score">
        {job.fit_score != null ? (
          <span className="font-mono font-semibold tabular-nums text-accent">{job.fit_score}</span>
        ) : (
          "—"
        )}
      </DetailRow>
      <DetailRow label="Site">{job.site ?? "—"}</DetailRow>
      <DetailRow label="Location">{job.location ?? "—"}</DetailRow>
      <DetailRow label="Discovered">{formatWhen(job.discovered_at)}</DetailRow>
      <DetailRow label="Scored">{formatWhen(job.scored_at)}</DetailRow>
      {job.tailored_resume_path ? (
        <DetailRow label="Resume PDF">
          <span className="break-all font-mono text-xs">{job.tailored_resume_path}</span>
        </DetailRow>
      ) : null}
      {job.apply_status ? <DetailRow label="Apply status">{job.apply_status}</DetailRow> : null}
      {job.detail_error ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Enrich error</p>
          <p className="mt-1 text-xs text-warn">{job.detail_error}</p>
        </div>
      ) : null}
      {job.score_reasoning ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Reasoning</p>
          <p className="mt-1 text-xs leading-relaxed text-ink-2">{job.score_reasoning}</p>
        </div>
      ) : null}
      {job.url ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">URL</p>
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 block break-all font-mono text-xs text-accent hover:underline"
          >
            {job.url}
          </a>
        </div>
      ) : null}
    </>
  );
}

function ApplicationAudit({
  application,
  detail,
  isUnverified,
}: {
  application: Application;
  detail: ApplicationDetail | null;
  isUnverified: boolean;
}) {
  return (
    <>
      <DetailRow label="Status">{application.apply_status ?? "—"}</DetailRow>
      <DetailRow label="Applied">{formatWhen(application.applied_at)}</DetailRow>
      <DetailRow label="Verification">{application.verification_confidence ?? "—"}</DetailRow>
      {application.apply_error ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Apply error</p>
          <p className="mt-1 text-xs text-warn">{application.apply_error}</p>
        </div>
      ) : null}
      {isUnverified ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-btn bg-good/15 px-3 py-1 text-xs text-good"
            onClick={() => void fetchConfirmApplication(application.url)}
          >
            Confirm
          </button>
          <button
            type="button"
            className="rounded-btn bg-warn/15 px-3 py-1 text-xs text-warn"
            onClick={() => void fetchRetryApplication(application.url)}
          >
            Retry
          </button>
        </div>
      ) : null}
      {detail?.log_detail?.parsed?.fields?.length ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Form snapshot</p>
          <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto font-mono text-[10px]">
            {detail.log_detail.parsed.fields.map((f) => (
              <li key={f.label} className="flex justify-between gap-2">
                <span className="text-ink-4">{f.label}</span>
                <span>{f.value || "—"}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {detail?.log_detail?.log_excerpt ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Log excerpt</p>
          <pre className="mt-1 max-h-48 overflow-auto rounded border border-panel-border bg-canvas p-2 font-mono text-[10px] text-ink-3">
            {detail.log_detail.log_excerpt}
          </pre>
        </div>
      ) : null}
    </>
  );
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">{label}</p>
      <div className="mt-1 text-ink-2">{children}</div>
    </div>
  );
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
