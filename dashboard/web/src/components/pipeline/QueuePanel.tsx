import type { Job } from "../../api";
import { jobPipelineStage, stageBadgeClass } from "../../utils/jobPipeline";

/** Job fields shown in the apply queue (subset of {@link Job}). */
export type QueueJob = Pick<
  Job,
  "url" | "title" | "site" | "fit_score" | "tailored_resume_path"
> & {
  application_url?: string | null;
} & Partial<
    Pick<
      Job,
      | "apply_status"
      | "applied_at"
      | "cover_letter_path"
      | "tailor_attempts"
      | "full_description"
      | "detail_error"
      | "apply_attempts"
    >
  >;

type Props = {
  jobs: QueueJob[];
  /** Total queue depth for "next N of M" header; defaults to `jobs.length`. */
  queueDepth?: number;
  maxItems?: number;
  isLoading?: boolean;
  onApplyNow?: (job: QueueJob) => void;
  onSkip?: (job: QueueJob) => void;
  onViewPrompt?: (job: QueueJob) => void;
  /** Empty-state primary action (e.g. start discover). */
  onDiscover?: () => void;
};

const ATS_RULES: { label: string; fragments: string[] }[] = [
  { label: "Greenhouse", fragments: ["greenhouse.io", "grnh.se"] },
  { label: "Lever", fragments: ["lever.co"] },
  { label: "Ashby", fragments: ["ashbyhq.com"] },
  { label: "Workday", fragments: ["myworkdayjobs.com", "workday.com"] },
  { label: "iCIMS", fragments: ["icims.com"] },
  { label: "SmartRecruiters", fragments: ["smartrecruiters.com"] },
  { label: "Jobvite", fragments: ["jobvite.com"] },
  { label: "BambooHR", fragments: ["bamboohr.com"] },
  { label: "Workable", fragments: ["workable.com"] },
  { label: "WaaS", fragments: ["workatastartup.com"] },
];

const QUEUE_GRID =
  "grid grid-cols-[2rem_minmax(0,1fr)_5.5rem_6.5rem_minmax(7.5rem,auto)_2.5rem] items-center gap-x-3 border-t border-panel-border text-[14px] leading-snug";

function detectAts(job: QueueJob): string | null {
  const lower = (job.application_url ?? job.url ?? "").trim().toLowerCase();
  if (!lower) return null;
  for (const rule of ATS_RULES) {
    if (rule.fragments.some((fragment) => lower.includes(fragment))) {
      return rule.label;
    }
  }
  return null;
}

function queueJobForPipeline(job: QueueJob): Job {
  return {
    url: job.url,
    title: job.title,
    site: job.site,
    location: null,
    salary: null,
    fit_score: job.fit_score,
    score_reasoning: null,
    discovered_at: null,
    scored_at: null,
    activity_at: null,
    detail_error: job.detail_error ?? null,
    full_description: job.full_description ?? null,
    tailored_resume_path: job.tailored_resume_path ?? null,
    tailored_at: null,
    tailor_attempts: job.tailor_attempts ?? null,
    cover_letter_path: job.cover_letter_path ?? null,
    applied_at: job.applied_at ?? null,
    apply_status: job.apply_status ?? null,
    apply_attempts: job.apply_attempts ?? null,
  };
}

function scoreCell(score: number | null) {
  if (score == null) {
    return <span className="font-mono tabular-nums text-ink-4">—</span>;
  }
  const tone =
    score >= 8 ? "text-ok" : score >= 6 ? "text-warn" : "text-ink-3";
  return (
    <span className={`font-mono text-base font-medium tabular-nums ${tone}`}>
      {score.toFixed(1)}
    </span>
  );
}

function QueueRow({
  job,
  index,
  onApplyNow,
  onSkip,
  onViewPrompt,
}: {
  job: QueueJob;
  index: number;
  onApplyNow?: (job: QueueJob) => void;
  onSkip?: (job: QueueJob) => void;
  onViewPrompt?: (job: QueueJob) => void;
}) {
  const ats = detectAts(job);
  const stage = jobPipelineStage(queueJobForPipeline(job));

  return (
    <div className={`${QUEUE_GRID} bg-canvas px-3 py-2.5 transition-colors hover:bg-panel-hover`}>
      <span className="font-mono text-[11px] tabular-nums text-ink-4">
        {String(index + 1).padStart(2, "0")}
      </span>
      <div className="min-w-0">
        <p className="truncate font-medium text-ink" title={job.title ?? job.url}>
          {job.title ?? "Untitled"}
        </p>
        <p className="truncate text-[12px] text-ink-3">{job.site ?? "—"}</p>
      </div>
      <div>
        {ats ? (
          <span className="inline-block max-w-full truncate rounded-[var(--rad-chip)] bg-panel-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-ink-2 ring-1 ring-panel-border">
            {ats}
          </span>
        ) : (
          <span className="font-mono text-[11px] text-ink-4">—</span>
        )}
      </div>
      <div>
        <span
          className={`inline-block max-w-full truncate rounded-[var(--rad-chip)] px-1.5 py-0.5 text-[10px] font-medium ${stageBadgeClass(stage)}`}
          title={stage}
        >
          {stage}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-1">
        {onApplyNow && (
          <button
            type="button"
            className="rounded-[var(--rad-btn)] bg-accent/15 px-2 py-1 text-[11px] font-medium text-accent ring-1 ring-accent/30 hover:bg-accent/25"
            onClick={() => onApplyNow(job)}
          >
            Apply now
          </button>
        )}
        {onViewPrompt && (
          <button
            type="button"
            className="rounded-[var(--rad-btn)] px-2 py-1 text-[11px] text-ink-2 ring-1 ring-panel-border hover:bg-panel-elevated hover:text-ink"
            onClick={() => onViewPrompt(job)}
          >
            View prompt
          </button>
        )}
        {onSkip && (
          <button
            type="button"
            className="rounded-[var(--rad-btn)] px-2 py-1 text-[11px] text-ink-3 ring-1 ring-panel-border hover:bg-panel-elevated hover:text-ink-2"
            onClick={() => onSkip(job)}
          >
            Skip
          </button>
        )}
      </div>
      <div className="text-right">{scoreCell(job.fit_score)}</div>
    </div>
  );
}

function QueueSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={`${QUEUE_GRID} px-3 py-2.5`}>
          <div className="skeleton h-3 w-5" />
          <div className="space-y-1.5">
            <div className="skeleton h-3.5 w-4/5 max-w-[220px]" />
            <div className="skeleton h-3 w-1/3 max-w-[100px]" />
          </div>
          <div className="skeleton h-5 w-14" />
          <div className="skeleton h-5 w-12" />
          <div className="skeleton h-6 w-24 justify-self-end" />
          <div className="skeleton ml-auto h-5 w-8" />
        </div>
      ))}
    </>
  );
}

export function QueuePanel({
  jobs,
  queueDepth,
  maxItems = 10,
  isLoading,
  onApplyNow,
  onSkip,
  onViewPrompt,
  onDiscover,
}: Props) {
  const visible = jobs.slice(0, maxItems);
  const total = queueDepth ?? jobs.length;
  const hasActions = Boolean(onApplyNow || onSkip || onViewPrompt);

  return (
    <section className="flex min-h-0 flex-col" aria-label="Apply queue">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-3">
            Up next
          </p>
          <h2 className="font-display text-lg font-normal tracking-tight text-ink">
            {total > 0
              ? `Queue — next ${visible.length} of ${total}`
              : "Queue"}
          </h2>
        </div>
        {total > maxItems && (
          <p className="font-mono text-[11px] tabular-nums text-ink-4">
            +{total - maxItems} more
          </p>
        )}
      </div>

      <div className="overflow-hidden rounded-[var(--rad-card)] ring-1 ring-panel-border">
        <div
          className={`${QUEUE_GRID} border-b border-panel-border bg-panel px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-ink-4`}
        >
          <span>#</span>
          <span>Role</span>
          <span>ATS</span>
          <span>Stage</span>
          <span className={hasActions ? "text-right" : "sr-only"}>Actions</span>
          <span className="text-right">Fit</span>
        </div>

        <div className="max-h-[min(42vh,420px)] overflow-y-auto scroll-thin bg-panel">
          {isLoading ? (
            <QueueSkeleton />
          ) : visible.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <p className="text-[14px] text-ink-2">
                No jobs in the apply queue yet. Run discover, then score and tailor so roles are
                ready to apply.
              </p>
              {onDiscover ? (
                <button
                  type="button"
                  className="mt-4 rounded-[var(--rad-btn)] bg-accent/15 px-4 py-2 text-[13px] font-medium text-accent ring-1 ring-accent/30 hover:bg-accent/25"
                  onClick={onDiscover}
                >
                  Run discover
                </button>
              ) : (
                <p className="mt-3 font-mono text-[12px] text-ink-4">
                  Start a pipeline run from the control bar, or run{" "}
                  <code className="text-ink-3">applypilot run</code> in the terminal.
                </p>
              )}
            </div>
          ) : (
            visible.map((job, i) => (
              <QueueRow
                key={job.url}
                job={job}
                index={i}
                onApplyNow={onApplyNow}
                onSkip={onSkip}
                onViewPrompt={onViewPrompt}
              />
            ))
          )}
        </div>
      </div>
    </section>
  );
}
