import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchJobs, fetchTriageCounts, fetchStats, type Job } from "../api";
import {
  JOB_TRIAGE_FILTERS,
  jobTriageLabel,
  normalizeTriageStageParam,
  triageFilterCount,
} from "../utils/jobTriage";
import {
  composeJobSort,
  jobSortDirOptions,
  jobSortFieldLabel,
  jobSortFieldOptions,
  parseJobSort,
  type JobSortDir,
  type JobSortField,
} from "../utils/jobSort";
import { isPriorityBoardName, sortByPriorityName } from "../utils/sitePriority";
import { formatJobAge, statusbarClass } from "../utils/statusbar";
import { useDebouncedValue } from "../utils/useDebouncedValue";
import { VirtualScroll } from "./VirtualScroll";
import { JobDetailPane } from "./JobDetailPane";
import { PageCanvas } from "./layout/PageCanvas";

const PAGE_SIZES = [25, 50, 100] as const;
const JOB_ROW_PX = 58;

type Props = {
  searchParams: URLSearchParams;
  onSearchParamsChange: (next: URLSearchParams) => void;
  onJobSelect?: (job: Job) => void;
};

function normalizePageSize(raw: number): number {
  return (PAGE_SIZES as readonly number[]).includes(raw) ? raw : 50;
}

function parseFilters(sp: URLSearchParams) {
  const minScore = Number(sp.get("min_score") ?? "0") || 0;
  const site = sp.get("site") ?? "";
  const search = sp.get("search") ?? "";
  const stage = normalizeTriageStageParam(sp.get("stage") ?? "");
  const sort = parseJobSort(sp.get("sort"), stage).apiSort;
  const applyStatus = sp.get("apply_status") ?? "";
  const lowScoreReason = sp.get("low_score_reason") ?? "";
  const limit = normalizePageSize(Number(sp.get("limit") ?? "50") || 50);
  const page = Math.max(1, Number(sp.get("page") ?? "1") || 1);
  return { stage, minScore, site, search, sort, applyStatus, lowScoreReason, limit, page };
}

export function JobsExplorerPage({ searchParams, onSearchParamsChange, onJobSelect }: Props) {
  const paramsKey = searchParams.toString();
  const filters = useMemo(() => parseFilters(searchParams), [paramsKey]);
  const [searchInput, setSearchInput] = useState(() => filters.search);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const debouncedSearch = useDebouncedValue(searchInput, 300);
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // Advanced filters are hidden in the UI; stale URL params caused chip counts ≠ list.
  useEffect(() => {
    if (
      filters.minScore > 0 ||
      filters.site ||
      filters.search ||
      filters.applyStatus
    ) {
      patchParams({
        min_score: null,
        site: null,
        search: null,
        apply_status: null,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
  }, []);

  useEffect(() => {
    if (debouncedSearch === filters.search) return;
    patchParams({ search: debouncedSearch || null, page: 1 });
  }, [debouncedSearch, filters.search, patchParams]);

  const querySearch = debouncedSearch.trim();
  const stageSlug = filters.stage;

  const sortFieldOptions = useMemo(
    () => jobSortFieldOptions(stageSlug),
    [stageSlug],
  );

  useEffect(() => {
    const parsed = parseJobSort(filters.sort, stageSlug);
    if (sortFieldOptions.includes(parsed.field)) return;
    patchParams({ sort: composeJobSort("activity", "desc"), page: 1 });
  }, [filters.sort, stageSlug, sortFieldOptions, patchParams]);

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
    refetchInterval: 15_000,
  });

  const triageCountsKey = [
    "jobs-triage-counts",
    filters.minScore,
    filters.site,
    querySearch,
    filters.applyStatus,
    filters.lowScoreReason,
  ] as const;

  const { data: triageCounts } = useQuery({
    queryKey: triageCountsKey,
    queryFn: () =>
      fetchTriageCounts({
        min_score: filters.minScore > 0 ? filters.minScore : undefined,
        site: filters.site || undefined,
        search: querySearch || undefined,
        apply_status: filters.applyStatus || undefined,
        low_score_reason: filters.lowScoreReason || undefined,
      }),
    refetchInterval: 15_000,
  });

  const jobsQueryKey = [
    "jobs",
    stageSlug,
    filters.minScore,
    filters.site,
    querySearch,
    filters.sort,
    filters.applyStatus,
    filters.lowScoreReason,
    filters.limit,
    filters.page,
  ] as const;

  const { data, isPending, isFetching, refetch } = useQuery({
    queryKey: jobsQueryKey,
    queryFn: () =>
      fetchJobs({
        stage: stageSlug || undefined,
        min_score: filters.minScore > 0 ? filters.minScore : undefined,
        site: filters.site || undefined,
        search: querySearch || undefined,
        apply_status: filters.applyStatus || undefined,
        low_score_reason: filters.lowScoreReason || undefined,
        sort: filters.sort,
        limit: filters.limit,
        page: filters.page,
      }),
    staleTime: 0,
    refetchInterval: 15_000,
  });

  const pageAligned = data == null || data.page === filters.page;
  const jobs = pageAligned ? (data?.jobs ?? []) : [];
  const total = pageAligned ? (data?.total ?? 0) : 0;
  const pages = pageAligned
    ? (data?.pages ?? (total > 0 ? Math.ceil(total / filters.limit) : 0))
    : 0;
  const currentPage = pageAligned ? (data?.page ?? filters.page) : filters.page;
  const listLoading = isPending || (isFetching && jobs.length === 0);
  const pageStart = total === 0 ? 0 : (currentPage - 1) * filters.limit + 1;
  const pageEnd = total === 0 ? 0 : Math.min(currentPage * filters.limit, total);

  useEffect(() => {
    if (!pageAligned || pages === 0) return;
    if (filters.page > pages) {
      patchParams({ page: pages });
    }
  }, [filters.page, pages, pageAligned, patchParams]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: 0 });
  }, [currentPage, stageSlug, filters.limit]);

  const siteOptions = useMemo(() => {
    const rows = sortByPriorityName(
      (stats?.by_site ?? []).map((r) => ({ site: r.site ?? "", source: r.site ?? "" })),
    );
    return rows.map((r) => r.site).filter((s): s is string => Boolean(s));
  }, [stats?.by_site]);

  const stageChips = JOB_TRIAGE_FILTERS;
  const lowScoreReasons = stats?.low_score_reasons ?? [];
  const sortState = useMemo(
    () => parseJobSort(filters.sort, stageSlug),
    [filters.sort, stageSlug],
  );
  const sortDirOptions = useMemo(
    () => jobSortDirOptions(sortState.field),
    [sortState.field],
  );

  const setSort = useCallback(
    (field: JobSortField, dir: JobSortDir) => {
      patchParams({ sort: composeJobSort(field, dir), page: 1 });
    },
    [patchParams],
  );

  const selectJob = useCallback(
    (job: Job) => {
      setSelectedJob(job);
      onJobSelect?.(job);
    },
    [onJobSelect],
  );

  useEffect(() => {
    if (jobs.length === 0) {
      setSelectedJob(null);
      return;
    }
    if (!selectedJob || !jobs.some((j) => j.url === selectedJob.url)) {
      setSelectedJob(jobs[0]);
      onJobSelect?.(jobs[0]);
    }
  }, [jobs, selectedJob, onJobSelect]);

  const resetListFilters = useCallback(
    () =>
      patchParams({
        stage: null,
        min_score: null,
        site: null,
        search: null,
        apply_status: null,
        low_score_reason: null,
        page: 1,
      }),
    [patchParams],
  );

  return (
    <PageCanvas wide>
      <div className="jobs">
        <div className="jobs__list">
          <div className="jobs__filterbar">
            {stageChips.map((c) => {
              const on = c.slug === filters.stage;
              let count = triageFilterCount(c.slug, triageCounts, stats);
              if (on && pageAligned && total >= 0) {
                count = total;
              }
              return (
                <button
                  key={c.slug || "__all"}
                  type="button"
                  className={on ? "chip chip--on" : "chip"}
                  onClick={() =>
                    patchParams({
                      stage: c.slug || null,
                      min_score: null,
                      site: null,
                      search: null,
                      apply_status: null,
                      page: 1,
                    })
                  }
                >
                  {c.label}
                  <span className="chip__count">{count}</span>
                </button>
              );
            })}
          </div>

          {lowScoreReasons.length > 0 ? (
            <div className="jobs__reasons" aria-label="Common low-score reasons">
              <span className="jobs__reasons-label">Below 7 because</span>
              {lowScoreReasons.slice(0, 8).map((row) => {
                const active = filters.lowScoreReason === row.reason;
                return (
                  <button
                    key={row.reason}
                    type="button"
                    className={active ? "chip chip--on" : "chip"}
                    title={`${row.count} job${row.count === 1 ? "" : "s"} — click to filter`}
                    aria-pressed={active}
                    onClick={() =>
                      patchParams({
                        low_score_reason: active ? null : row.reason,
                        page: 1,
                      })
                    }
                  >
                    {row.reason}
                    <span className="chip__count">{row.count}</span>
                  </button>
                );
              })}
            </div>
          ) : null}

          <div className="jobs__sortbar" aria-label="Sort jobs list">
            <label className="control jobs__sort-control">
              <span className="control__label">Sort by</span>
              <select
                className="control__select"
                value={sortState.field}
                onChange={(e) => {
                  const field = e.target.value as JobSortField;
                  const dirs = jobSortDirOptions(field);
                  const dir = dirs.some((d) => d.value === sortState.dir)
                    ? sortState.dir
                    : dirs[0]?.value ?? "desc";
                  setSort(field, dir);
                }}
              >
                {sortFieldOptions.map((field) => (
                  <option key={field} value={field}>
                    {jobSortFieldLabel(field)}
                  </option>
                ))}
              </select>
            </label>
            <label className="control jobs__sort-control">
              <span className="control__label">Order</span>
              <select
                className="control__select"
                value={sortState.dir}
                disabled={sortState.field === "apply_priority"}
                onChange={(e) => setSort(sortState.field, e.target.value as JobSortDir)}
              >
                {sortDirOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="jobs__filterbar jobs__filterbar--advanced" hidden aria-hidden>
            <label className="control" style={{ flex: 1, minWidth: 140 }}>
              <span className="control__label">Search</span>
              <input
                className="control__input"
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Title, company…"
              />
            </label>
            <label className="control">
              <span className="control__label">Site</span>
              <select
                className="control__select"
                value={filters.site}
                onChange={(e) => patchParams({ site: e.target.value || null, page: 1 })}
              >
                <option value="">All</option>
                {siteOptions.map((s) => (
                  <option key={s} value={s}>
                    {isPriorityBoardName(s) ? `${s} ★` : s}
                  </option>
                ))}
              </select>
            </label>
            <label className="control">
              <span className="control__label">Min score</span>
              <select
                className="control__select"
                value={String(filters.minScore)}
                onChange={(e) =>
                  patchParams({ min_score: Number(e.target.value) || 0, page: 1 })
                }
              >
                <option value="0">Any</option>
                <option value="6">6+</option>
                <option value="7">7+</option>
                <option value="8">8+</option>
                <option value="9">9+</option>
              </select>
            </label>
            <div className="control" style={{ alignSelf: "flex-end" }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void refetch()}>
                Refresh
              </button>
            </div>
          </div>

          <div className="jobs__pager" aria-label="Jobs list pagination">
            <label className="control jobs__pager-size">
              <span className="control__label">Per page</span>
              <select
                className="control__select"
                value={String(filters.limit)}
                onChange={(e) =>
                  patchParams({ limit: normalizePageSize(Number(e.target.value)), page: 1 })
                }
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={String(n)}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <p className="jobs__pager-meta panel__sub">
              {total === 0 ? (
                "No jobs"
              ) : (
                <>
                  Showing <strong>{pageStart}</strong>–<strong>{pageEnd}</strong> of{" "}
                  <strong>{total}</strong>
                  {pages > 1 ? (
                    <>
                      {" "}
                      · page <strong>{currentPage}</strong> of <strong>{pages}</strong>
                    </>
                  ) : null}
                  {listLoading ? " · loading…" : null}
                </>
              )}
            </p>
            <div className="jobs__pager-actions">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={currentPage <= 1 || listLoading}
                onClick={() => patchParams({ page: currentPage - 1 })}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={pages === 0 || currentPage >= pages || listLoading}
                onClick={() => patchParams({ page: currentPage + 1 })}
              >
                Next
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => void refetch()}
                disabled={listLoading}
              >
                Refresh
              </button>
            </div>
          </div>

          {listLoading ? (
            <div className="jobs__scroll">
              <p className="panel__sub" style={{ padding: 16 }}>
                Loading jobs…
              </p>
            </div>
          ) : jobs.length === 0 ? (
            <div className="jobs__scroll">
              <p className="panel__sub" style={{ padding: 16 }}>
                No jobs match these filters.
                {filters.stage || filters.minScore || filters.site || filters.search ? (
                  <>
                    {" "}
                    <button type="button" className="btn btn--ghost btn--sm" onClick={resetListFilters}>
                      Clear filters
                    </button>
                  </>
                ) : null}
              </p>
            </div>
          ) : (
            <VirtualScroll
              key={`${stageSlug}|${filters.page}|${filters.limit}|${filters.sort}|${filters.lowScoreReason}|${querySearch}`}
              scrollRef={scrollRef}
              className="jobs__scroll"
              items={jobs}
              getItemKey={(job) => job.url}
              estimateSize={JOB_ROW_PX}
              overscan={16}
            >
              {(job) => (
                <JobListRow
                  job={job}
                  selected={selectedJob?.url === job.url}
                  onSelect={() => selectJob(job)}
                />
              )}
            </VirtualScroll>
          )}
        </div>

        <JobDetailPane job={selectedJob} />
      </div>
    </PageCanvas>
  );
}

function JobListRow({
  job,
  selected,
  onSelect,
}: {
  job: Job;
  selected: boolean;
  onSelect: () => void;
}) {
  const stage = jobTriageLabel(job);
  const score = job.fit_score;
  const scoreClass =
    score != null && score >= 8.5 ? "job__score job__score--strong" : "job__score";
  const rawDate = job.activity_at ?? job.discovered_at ?? job.scored_at ?? null;
  const metaParts = [job.site, job.location, job.salary].filter(Boolean);

  return (
    <button
      type="button"
      className={selected ? "job-row job-row--selected" : "job-row"}
      onClick={onSelect}
    >
      <span className={statusbarClass(stage)}>{stage}</span>
      <div className="job__main">
        <div className="job__title-line">
          <span className="job__title">{job.title ?? "Untitled"}</span>
        </div>
        <div className="job__meta">{metaParts.length ? metaParts.join(" · ") : "—"}</div>
      </div>
      <div className="job__right">
        <div className={scoreClass}>{score ?? "—"}</div>
        <div className="job__age">{formatJobAge(rawDate)}</div>
      </div>
    </button>
  );
}
