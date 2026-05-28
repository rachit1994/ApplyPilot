import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { fetchJobs, fetchStats, type Job } from "../api";
import { JOB_TRIAGE_FILTERS, jobTriageLabel, triageFilterCount } from "../utils/jobTriage";
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

function parseFilters(sp: URLSearchParams) {
  const minScore = Number(sp.get("min_score") ?? "0") || 0;
  const site = sp.get("site") ?? "";
  const search = sp.get("search") ?? "";
  const stage = sp.get("stage") ?? "";
  const sortParam = sp.get("sort");
  const sort = sortParam ?? (stage === "ready" ? "apply_priority" : "activity_desc");
  const applyStatus = sp.get("apply_status") ?? "";
  const limit = Number(sp.get("limit") ?? "50") || 50;
  return { stage, minScore, site, search, sort, applyStatus, limit };
}

export function JobsExplorerPage({ searchParams, onSearchParamsChange, onJobSelect }: Props) {
  const paramsKey = searchParams.toString();
  const filters = useMemo(() => parseFilters(searchParams), [paramsKey]);
  const [searchInput, setSearchInput] = useState(() => filters.search);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const debouncedSearch = useDebouncedValue(searchInput, 300);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fetchingMoreRef = useRef(false);

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
    patchParams({ search: debouncedSearch || null });
  }, [debouncedSearch, filters.search, patchParams]);

  const querySearch = debouncedSearch.trim();
  const pipelineStage =
    filters.stage === "tailored" || filters.stage === "ready" || filters.stage === "applied"
      ? (filters.stage as import("../api").PipelineStageFilter)
      : undefined;
  const stageSlug = pipelineStage ? "" : filters.stage;

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useInfiniteQuery({
      queryKey: [
        "jobs",
        stageSlug,
        pipelineStage ?? "",
        filters.minScore,
        filters.site,
        querySearch,
        filters.sort,
        filters.applyStatus,
        filters.limit,
      ],
      initialPageParam: 0,
      queryFn: ({ pageParam }) =>
        fetchJobs({
          stage: stageSlug || undefined,
          pipeline_stage: pipelineStage,
          min_score: filters.minScore > 0 ? filters.minScore : undefined,
          site: filters.site || undefined,
          search: querySearch || undefined,
          apply_status: filters.applyStatus || undefined,
          sort: filters.sort,
          limit: filters.limit,
          offset: Number(pageParam) * filters.limit,
        }),
      getNextPageParam: (lastPage, allPages) => {
        const loaded = allPages.reduce((n, p) => n + (p.jobs?.length ?? 0), 0);
        const total = lastPage.total ?? 0;
        if (loaded >= total) return undefined;
        return allPages.length;
      },
    });

  const jobs = useMemo(() => data?.pages.flatMap((p) => p.jobs ?? []) ?? [], [data?.pages]);
  const total = data?.pages?.[0]?.total ?? 0;

  const maybeLoadMore = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (!hasNextPage || isFetchingNextPage) return;
    if (fetchingMoreRef.current) return;
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (remaining > JOB_ROW_PX * 12) return;
    fetchingMoreRef.current = true;
    fetchNextPage()
      .catch(() => {})
      .finally(() => {
        fetchingMoreRef.current = false;
      });
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const siteOptions = useMemo(() => {
    const rows = sortByPriorityName(
      (stats?.by_site ?? []).map((r) => ({ site: r.site ?? "", source: r.site ?? "" })),
    );
    return rows.map((r) => r.site).filter((s): s is string => Boolean(s));
  }, [stats?.by_site]);

  const stageChips = JOB_TRIAGE_FILTERS;

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

  return (
    <PageCanvas wide>
      <div className="jobs">
        <div className="jobs__list">
          <div className="jobs__filterbar">
            {stageChips.map((c) => {
              const on = c.slug === filters.stage;
              const count = triageFilterCount(c.slug, stats);
              return (
                <button
                  key={c.slug || "__all"}
                  type="button"
                  className={on ? "chip chip--on" : "chip"}
                  onClick={() => patchParams({ stage: c.slug || null })}
                >
                  {c.label}
                  <span className="chip__count">{count}</span>
                </button>
              );
            })}
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
                onChange={(e) => patchParams({ site: e.target.value || null })}
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
                onChange={(e) => patchParams({ min_score: Number(e.target.value) || 0 })}
              >
                <option value="0">Any</option>
                <option value="6">6+</option>
                <option value="7">7+</option>
                <option value="8">8+</option>
                <option value="9">9+</option>
              </select>
            </label>
            <label className="control">
              <span className="control__label">Sort</span>
              <select
                className="control__select"
                value={filters.sort}
                onChange={(e) => patchParams({ sort: e.target.value })}
              >
                <option value="apply_priority">Apply priority</option>
                <option value="activity_desc">Activity ↓</option>
                <option value="fit_score_desc">Score ↓</option>
                <option value="discovered_at_desc">Discovered ↓</option>
              </select>
            </label>
            <label className="control">
              <span className="control__label">Page</span>
              <select
                className="control__select"
                value={String(filters.limit)}
                onChange={(e) => patchParams({ limit: Number(e.target.value) })}
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={String(n)}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <div className="control" style={{ alignSelf: "flex-end" }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void refetch()}>
                Refresh
              </button>
            </div>
          </div>

          {isLoading ? (
            <div className="jobs__scroll">
              <p className="panel__sub" style={{ padding: 16 }}>
                Loading jobs…
              </p>
            </div>
          ) : jobs.length === 0 ? (
            <div className="jobs__scroll">
              <p className="panel__sub" style={{ padding: 16 }}>
                No jobs match these filters.
              </p>
            </div>
          ) : (
            <VirtualScroll
              scrollRef={scrollRef}
              className="jobs__scroll"
              items={jobs}
              getItemKey={(job) => job.url}
              estimateSize={JOB_ROW_PX}
              overscan={16}
              onScroll={maybeLoadMore}
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

          {jobs.length > 0 ? (
            <div style={{ padding: "10px 12px" }}>
              <div className="panel__sub">
                Showing <strong>{jobs.length}</strong> of {total || "—"}
                {hasNextPage ? " · scrolling loads more" : " · end of list"}
                {isFetchingNextPage ? " · loading…" : null}
              </div>
              {hasNextPage ? (
                <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    disabled={isFetchingNextPage}
                    onClick={() => void fetchNextPage()}
                  >
                    {isFetchingNextPage ? "Loading…" : "Load more"}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
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
