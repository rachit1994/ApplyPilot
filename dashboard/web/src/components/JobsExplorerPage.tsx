import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchJobs, fetchStats, type Job } from "../api";
import { formatTime } from "../utils/format";
import {
  cellValue,
  gridTemplateColumns,
  JOB_STAGE_FILTER_OPTIONS,
  visibleJobColumns,
  type JobColumnDef,
} from "../utils/jobsTableColumns";
import { stageBadgeClass, jobPipelineStage } from "../utils/jobPipeline";
import { isPriorityBoardName, sortByPriorityName } from "../utils/sitePriority";
import { useDebouncedValue } from "../utils/useDebouncedValue";
import { VirtualScroll } from "./VirtualScroll";

const PAGE_SIZES = [25, 50, 100] as const;
const ROW_HEIGHT_PX = 52;

type Props = {
  searchParams: URLSearchParams;
  onSearchParamsChange: (next: URLSearchParams) => void;
  onJobSelect?: (job: Job) => void;
};

function parseFilters(sp: URLSearchParams) {
  const minScore = Number(sp.get("min_score") ?? "0") || 0;
  const site = sp.get("site") ?? "";
  const search = sp.get("search") ?? "";
  const stage = sp.get("stage") ?? "";
  const sortParam = sp.get("sort");
  const sort = sortParam ?? (stage === "ready" ? "apply_priority" : "activity_desc");
  const applyStatus = sp.get("apply_status") ?? "";
  const limit = Number(sp.get("limit") ?? "50") || 50;
  const page = Math.max(1, Number(sp.get("page") ?? "1") || 1);
  return { stage, minScore, site, search, sort, applyStatus, limit, page };
}

export function JobsExplorerPage({ searchParams, onSearchParamsChange, onJobSelect }: Props) {
  const paramsKey = searchParams.toString();
  const filters = useMemo(() => parseFilters(searchParams), [paramsKey]);
  const [searchInput, setSearchInput] = useState(() => filters.search);
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const patchParams = useCallback(
    (patch: Record<string, string | number | null | undefined>) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(patch)) {
        if (value == null || value === "" || (key === "min_score" && value === 0)) {
          next.delete(key);
        } else {
          next.set(key, String(value));
        }
      }
      onSearchParamsChange(next);
    },
    [searchParams, onSearchParamsChange],
  );

  useEffect(() => {
    setSearchInput(filters.search);
  }, [filters.search]);

  useEffect(() => {
    if (debouncedSearch === filters.search) return;
    patchParams({ search: debouncedSearch || null, page: 1 });
  }, [debouncedSearch, filters.search, patchParams]);

  const querySearch = debouncedSearch.trim();
  const offset = (filters.page - 1) * filters.limit;

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const { data, isLoading, isFetching } = useQuery({
    queryKey: [
      "jobs",
      filters.stage,
      filters.minScore,
      filters.site,
      querySearch,
      filters.sort,
      filters.applyStatus,
      filters.limit,
      offset,
    ],
    queryFn: () =>
      fetchJobs({
        stage: filters.stage || undefined,
        min_score: filters.minScore > 0 ? filters.minScore : undefined,
        site: filters.site || undefined,
        search: querySearch || undefined,
        apply_status: filters.applyStatus || undefined,
        sort: filters.sort,
        limit: filters.limit,
        offset,
      }),
  });

  const jobs = data?.jobs ?? [];
  const total = data?.total ?? 0;
  const columns = useMemo(() => visibleJobColumns(filters.stage), [filters.stage]);
  const gridCols = useMemo(() => gridTemplateColumns(columns), [columns]);

  const pageCount = Math.max(1, Math.ceil(total / filters.limit));
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + filters.limit, total);

  const siteOptions = useMemo(() => {
    const rows = sortByPriorityName(
      (stats?.by_site ?? []).map((r) => ({ site: r.site ?? "", source: r.site ?? "" })),
    );
    return rows.map((r) => r.site).filter((s): s is string => Boolean(s));
  }, [stats?.by_site]);

  return (
    <div className="space-y-4 pb-8">
      <div className="flex flex-wrap items-end gap-3 rounded-card border border-panel-border bg-panel p-4">
        <FilterSelect
          label="Stage"
          value={filters.stage}
          onChange={(v) => patchParams({ stage: v, page: 1 })}
          options={JOB_STAGE_FILTER_OPTIONS.map((o) => ({
            value: o.slug,
            label: o.label,
          }))}
        />
        <FilterSelect
          label="Min score"
          value={String(filters.minScore)}
          onChange={(v) => patchParams({ min_score: Number(v) || 0, page: 1 })}
          options={[
            { value: "0", label: "Any" },
            { value: "6", label: "6+" },
            { value: "7", label: "7+" },
            { value: "8", label: "8+" },
            { value: "9", label: "9+" },
          ]}
        />
        <FilterSelect
          label="Site"
          value={filters.site}
          onChange={(v) => patchParams({ site: v, page: 1 })}
          options={[
            { value: "", label: "All sites" },
            ...siteOptions.map((s) => ({
              value: s,
              label: isPriorityBoardName(s) ? `${s} ★` : s,
            })),
          ]}
        />
        <FilterSelect
          label="Sort"
          value={filters.sort}
          onChange={(v) => patchParams({ sort: v, page: 1 })}
          options={[
            { value: "apply_priority", label: "Apply priority (Naukri first)" },
            { value: "activity_desc", label: "Activity ↓" },
            { value: "fit_score_desc", label: "Score ↓" },
            { value: "fit_score_asc", label: "Score ↑" },
            { value: "discovered_at_desc", label: "Discovered ↓" },
            { value: "title_asc", label: "Title A–Z" },
          ]}
        />
        <FilterSelect
          label="Page size"
          value={String(filters.limit)}
          onChange={(v) => patchParams({ limit: Number(v), page: 1 })}
          options={PAGE_SIZES.map((n) => ({ value: String(n), label: String(n) }))}
        />
        <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[10px] font-medium uppercase tracking-wide text-ink-4">
          Search
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Title, site, location…"
            className="rounded-btn border border-panel-border bg-canvas px-2 py-1.5 text-sm normal-case text-ink"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
        <span>
          {isFetching && !isLoading ? "Refreshing…" : null}
          Page {filters.page} · {rangeStart}–{rangeEnd} of {total}
          {filters.stage ? ` · stage filter` : ""}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={filters.page <= 1}
            onClick={() => patchParams({ page: filters.page - 1 })}
            className="rounded-btn border border-panel-border px-3 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <button
            type="button"
            disabled={filters.page >= pageCount}
            onClick={() => patchParams({ page: filters.page + 1 })}
            className="rounded-btn border border-panel-border px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-card border border-panel-border bg-panel">
        <div
          className="grid items-center border-b border-panel-border text-[10px] font-medium uppercase tracking-wide text-ink-4"
          style={{ gridTemplateColumns: gridCols }}
        >
          {columns.map((col) => (
            <div key={col.id} className="px-3 py-2">
              {col.label}
            </div>
          ))}
        </div>
        <JobsVirtualBody
          jobs={jobs}
          columns={columns}
          gridCols={gridCols}
          isLoading={isLoading}
          onJobSelect={onJobSelect}
        />
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col gap-1 text-[10px] font-medium uppercase tracking-wide text-ink-4">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-[7rem] rounded-btn border border-panel-border bg-canvas px-2 py-1.5 text-sm normal-case text-ink"
      >
        {options.map((o) => (
          <option key={o.value || "__all"} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function JobsVirtualBody({
  jobs,
  columns,
  gridCols,
  isLoading,
  onJobSelect,
}: {
  jobs: Job[];
  columns: JobColumnDef[];
  gridCols: string;
  isLoading: boolean;
  onJobSelect?: (job: Job) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  if (isLoading) {
    return (
      <div className="px-3 py-8 text-center text-sm text-ink-3">Loading jobs…</div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-ink-3">No jobs match these filters.</div>
    );
  }

  return (
    <VirtualScroll
      items={jobs}
      scrollRef={scrollRef}
      getItemKey={(job) => job.url}
      estimateSize={ROW_HEIGHT_PX}
      className="scroll-thin max-h-[72vh] min-h-[24rem] overflow-y-auto overflow-x-hidden"
      innerClassName="relative w-full"
    >
      {(job) => (
        <JobGridRow
          job={job}
          columns={columns}
          gridCols={gridCols}
          onSelect={onJobSelect}
        />
      )}
    </VirtualScroll>
  );
}

function JobGridRow({
  job,
  columns,
  gridCols,
  onSelect,
}: {
  job: Job;
  columns: JobColumnDef[];
  gridCols: string;
  onSelect?: (job: Job) => void;
}) {
  const stage = jobPipelineStage(job);

  return (
    <div
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect ? () => onSelect(job) : undefined}
      onKeyDown={
        onSelect
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(job);
              }
            }
          : undefined
      }
      className={`grid items-center border-t border-panel-border/60 text-sm transition-colors hover:bg-panel-elevated/80 ${
        onSelect ? "cursor-pointer" : ""
      }`}
      style={{ gridTemplateColumns: gridCols }}
    >
      {columns.map((col) => (
        <JobCell key={col.id} job={job} column={col} stage={stage} />
      ))}
    </div>
  );
}

function JobCell({
  job,
  column,
  stage,
}: {
  job: Job;
  column: JobColumnDef;
  stage: string;
}) {
  const id = column.id;

  if (id === "fit_score") {
    const score = job.fit_score;
    const color =
      score != null && score >= 8
        ? "text-emerald-400"
        : score != null && score >= 6
          ? "text-amber-300"
          : "text-ink-3";
    return (
      <div className="px-3 py-2 font-mono tabular-nums">
        <span className={color}>{score ?? "—"}</span>
      </div>
    );
  }

  if (id === "stage") {
    return (
      <div className="px-3 py-2">
        <span
          className={`inline-block max-w-full truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${stageBadgeClass(stage)}`}
        >
          {stage}
        </span>
      </div>
    );
  }

  if (id === "title") {
    return (
      <div className="min-w-0 px-3 py-2">
        <a
          href={job.url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="block truncate font-medium text-ink hover:text-accent"
          title={job.title ?? job.url}
        >
          {job.title ?? "Untitled"}
        </a>
      </div>
    );
  }

  if (id === "tailored_resume_path" || id === "cover_letter_path") {
    const path = job[id];
    return <PathCell path={path} />;
  }

  if (id === "application_url") {
    const url = job.application_url;
    if (!url) return <div className="px-3 py-2 text-ink-4">—</div>;
    return (
      <div className="min-w-0 px-3 py-2">
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="block truncate font-mono text-xs text-accent"
          title={url}
        >
          {url}
        </a>
      </div>
    );
  }

  if (id === "activity_at" || id === "discovered_at" || id === "scored_at" || id === "tailored_at" || id === "cover_letter_at" || id === "applied_at" || id === "last_attempted_at" || id === "detail_scraped_at") {
    const raw = job[id as keyof Job] as string | null | undefined;
    return (
      <div className="px-3 py-2 font-mono text-xs text-ink-3" title={raw ?? undefined}>
        {raw ? formatTime(raw) : "—"}
      </div>
    );
  }

  const text = cellValue(job, id);
  const truncate =
    id === "score_reasoning" || id === "detail_error" || id === "apply_error";

  return (
    <div
      className={`px-3 py-2 text-xs text-ink-3 ${truncate ? "min-w-0 truncate" : ""}`}
      title={truncate ? text : undefined}
    >
      {text}
    </div>
  );
}

function PathCell({ path }: { path: string | null | undefined }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);

  if (!path) {
    return <div className="px-3 py-2 font-mono text-xs text-ink-4">—</div>;
  }

  return (
    <div className="flex min-w-0 items-center gap-1 px-3 py-2">
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-2" title={path}>
        {path}
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void navigator.clipboard.writeText(path).then(() => setCopied(true));
        }}
        className="shrink-0 rounded px-1 py-0.5 text-[10px] text-accent hover:bg-accent/10"
        title="Copy path"
      >
        {copied ? "✓" : "⎘"}
      </button>
    </div>
  );
}
