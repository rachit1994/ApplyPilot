import type { Job, PipelineStageFilter } from "../api";
import { formatTime } from "../utils/format";
import { jobPipelineStage, stageBadgeClass } from "../utils/jobPipeline";
import { Input } from "./ui/input";
import { Select } from "./ui/select";
import { VirtualGrid } from "./VirtualScroll";

type Props = {
  jobs: Job[];
  recentJobs: Job[];
  minScoreFilter: number;
  onMinScoreChange: (n: number) => void;
  pipelineStageFilter: PipelineStageFilter;
  onPipelineStageChange: (stage: PipelineStageFilter) => void;
  search: string;
  onSearchChange: (q: string) => void;
  total: number;
  isLoading?: boolean;
  onJobSelect?: (job: Job) => void;
};

const JOBS_BODY_MAX_CLASS = "scroll-thin h-[72vh] min-h-[72vh] overflow-y-auto";

const JOB_GRID_CLASS =
  "grid grid-cols-[3.5rem_6.5rem_minmax(0,1fr)_7rem_8rem] items-center border-t border-panel-border text-sm transition-colors hover:bg-panel-elevated/60";

const STAGE_OPTIONS: { id: PipelineStageFilter; label: string }[] = [
  { id: "all", label: "All jobs" },
  { id: "tailored", label: "Tailored" },
  { id: "ready", label: "Ready to apply" },
  { id: "applied", label: "Applied" },
];

const JOB_HEADER_CLASS = `${JOB_GRID_CLASS} border-b border-panel-border-strong bg-canvas/95 text-[10px] font-medium uppercase tracking-wide text-ink-4 backdrop-blur-sm`;

const JOB_ROW_ESTIMATE_PX = 56;

function scoreBadge(score: number | null) {
  if (score == null) return <span className="text-ink-5">—</span>;
  const color =
    score >= 8 ? "text-success" : score >= 6 ? "text-warning" : "text-ink-4";
  return <span className={`font-mono font-semibold tabular-nums ${color}`}>{score}</span>;
}

function stageBadge(job: Job) {
  const stage = jobPipelineStage(job);
  return (
    <span
      className={`inline-block max-w-[6.5rem] truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${stageBadgeClass(stage)}`}
      title={stage}
    >
      {stage}
    </span>
  );
}

function TableSkeleton() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className={`${JOB_GRID_CLASS} hover:bg-transparent`}>
          <div className="px-4 py-3">
            <div className="skeleton h-4 w-6" />
          </div>
          <div className="px-4 py-3">
            <div className="skeleton h-4 w-12" />
          </div>
          <div className="px-4 py-3">
            <div className="skeleton h-4 w-full max-w-[200px]" />
          </div>
          <div className="px-4 py-3">
            <div className="skeleton h-4 w-16" />
          </div>
          <div className="px-4 py-3">
            <div className="skeleton h-4 w-20" />
          </div>
        </div>
      ))}
    </>
  );
}

function JobRow({ job, onSelect }: { job: Job; onSelect?: (job: Job) => void }) {
  const handleRowClick = () => onSelect?.(job);

  return (
    <>
      <div className="px-4 py-2.5">{scoreBadge(job.fit_score)}</div>
      <div className="px-4 py-2.5">{stageBadge(job)}</div>
      <div
        className={`min-w-0 px-4 py-2.5 ${onSelect ? "cursor-pointer" : ""}`}
        onClick={onSelect ? handleRowClick : undefined}
        onKeyDown={
          onSelect
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleRowClick();
                }
              }
            : undefined
        }
        role={onSelect ? "button" : undefined}
        tabIndex={onSelect ? 0 : undefined}
      >
        <a
          href={job.url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="block truncate text-accent hover:text-accent-2 hover:underline"
          title={job.score_reasoning ?? job.title ?? job.url}
        >
          {job.title ?? "Untitled"}
        </a>
        {job.location ? (
          <p className="truncate text-[10px] text-ink-5">{job.location}</p>
        ) : null}
      </div>
      <div className="px-4 py-2.5 text-xs text-ink-4">{job.site ?? "—"}</div>
      <div className="px-4 py-2.5 text-xs tabular-nums text-ink-4">
        {formatTime(job.activity_at ?? job.scored_at ?? job.discovered_at)}
      </div>
    </>
  );
}

const jobHeader = (
  <>
    <span className="px-4 py-2.5">Score</span>
    <span className="px-4 py-2.5">Stage</span>
    <span className="px-4 py-2.5">Role</span>
    <span className="px-4 py-2.5">Source</span>
    <span className="px-4 py-2.5">Date</span>
  </>
);

export function JobsTable({
  jobs,
  recentJobs,
  minScoreFilter,
  onMinScoreChange,
  pipelineStageFilter,
  onPipelineStageChange,
  search,
  onSearchChange,
  total,
  isLoading,
  onJobSelect,
}: Props) {
  const showEmpty = !isLoading && jobs.length === 0;
  const stageLabel =
    STAGE_OPTIONS.find((o) => o.id === pipelineStageFilter)?.label ?? "All jobs";

  return (
    <section className="panel flex flex-col overflow-hidden">
      <header className="panel-header flex-wrap">
        <h2 className="panel-title">Jobs</h2>
        <span className="text-[10px] text-ink-5">{total} matching</span>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-panel-border px-4 py-3">
        <Input
          type="search"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search title or company…"
          className="min-w-[12rem] flex-1"
        />
        <label className="flex items-center gap-2 text-xs text-ink-4">
          Stage
          <Select
            value={pipelineStageFilter}
            onChange={(e) =>
              onPipelineStageChange(e.target.value as PipelineStageFilter)
            }
            className="max-w-[10rem]"
          >
            {STAGE_OPTIONS.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex items-center gap-2 text-xs text-ink-4">
          Min score
          <Select
            value={minScoreFilter}
            onChange={(e) => onMinScoreChange(Number(e.target.value))}
          >
            {[0, 5, 6, 7, 8, 9].map((n) => (
              <option key={n} value={n}>
                {n === 0 ? "Any" : `≥ ${n}`}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {recentJobs.length > 0 ? (
        <div className="border-b border-panel-border px-4 py-2">
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-ink-5">
            Recent activity
          </p>
          <div className="scroll-thin max-h-24 space-y-1 overflow-y-auto text-xs">
            {recentJobs.slice(0, 6).map((j) => (
              <div key={j.url} className="flex justify-between gap-2">
                <span className="truncate text-ink-3">{j.title ?? j.url}</span>
                {scoreBadge(j.fit_score)}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {isLoading ? (
        <div className={JOBS_BODY_MAX_CLASS}>
          <div className={JOB_HEADER_CLASS}>{jobHeader}</div>
          <TableSkeleton />
        </div>
      ) : (
        <VirtualGrid
          items={jobs}
          getItemKey={(j) => j.url}
          estimateSize={JOB_ROW_ESTIMATE_PX}
          gridClassName={JOB_GRID_CLASS}
          headerClassName={JOB_HEADER_CLASS}
          header={jobHeader}
          className={JOBS_BODY_MAX_CLASS}
          empty={
            showEmpty ? (
              <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
                <p className="text-sm font-medium text-ink-3">No jobs match</p>
                <p className="mt-1 max-w-xs text-xs text-ink-5">
                  {search.trim()
                    ? "Try a different search, stage filter, or lower the minimum score."
                    : pipelineStageFilter !== "all"
                      ? `No jobs in “${stageLabel}”. Try “All jobs” or another stage.`
                      : "Run the pipeline to discover and score roles."}
                </p>
              </div>
            ) : null
          }
        >
          {(j) => <JobRow job={j} onSelect={onJobSelect} />}
        </VirtualGrid>
      )}
    </section>
  );
}
