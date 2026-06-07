import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApplications, fetchStats } from "../api";
import { useApplyRun } from "../hooks/useApplyRun";
import { ApplyRunPlanModal } from "./ApplyRunPlanModal";
import { ApplicationDetailPanel } from "./ApplicationDetailPanel";
import {
  ApplicationRowActions,
  type ApplyListActionInfo,
} from "./ApplicationRowActions";
import { PageCanvas } from "./layout/PageCanvas";
import { VirtualScroll } from "./VirtualScroll";
import {
  apiNeedsAttentionForFilter,
  apiStatusForFilter,
  applicationAttemptAt,
  applicationDateCaption,
  applicationReasonLine,
  applicationReasonTone,
  applicationsIncludeFailedForFilter,
  applyStatusFilterFromUrl,
  formatWhen,
  isClaudeEscalated,
  needsHumanIntervention,
  statusLabel,
  type ApplyStatusFilter,
} from "../utils/applicationAudit";
import { useDebouncedValue } from "../utils/useDebouncedValue";
import { companyInitials, companyLabelFromSite } from "../utils/jobFacts";
import { statusbarClass } from "../utils/statusbar";

const APP_ROW_PX = 56;
const PAGE_SIZES = [25, 50, 100] as const;

type SortKey = "recent" | "fit" | "attempts" | "duration" | "company" | "status";
type SortDir = "asc" | "desc";

const SORT_DEFAULT_DIR: Record<SortKey, SortDir> = {
  recent: "desc",
  fit: "desc",
  attempts: "desc",
  duration: "desc",
  company: "asc",
  status: "asc",
};

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "recent", label: "Most recent" },
  { key: "fit", label: "Fit score" },
  { key: "attempts", label: "Attempts" },
  { key: "duration", label: "Duration" },
  { key: "company", label: "Company" },
];

type Props = {
  searchParams: URLSearchParams;
  onSearchParamsChange: (next: URLSearchParams) => void;
  showApplyControls?: boolean;
};

function normalizePageSize(raw: number): number {
  return (PAGE_SIZES as readonly number[]).includes(raw) ? raw : 50;
}

function parseAppsParams(sp: URLSearchParams) {
  const filter = applyStatusFilterFromUrl(sp.get("filter"));
  const search = sp.get("search") ?? "";
  const limit = normalizePageSize(Number(sp.get("limit") ?? "50") || 50);
  const page = Math.max(1, Number(sp.get("page") ?? "1") || 1);
  return { filter, search, limit, page };
}

export function AppliedApplicationsPage({
  searchParams,
  onSearchParamsChange,
  showApplyControls = false,
}: Props) {
  const applyRun = useApplyRun();
  const [applyPlanOpen, setApplyPlanOpen] = useState(false);
  const paramsKey = searchParams.toString();
  const filters = useMemo(() => parseAppsParams(searchParams), [paramsKey]);
  const [searchInput, setSearchInput] = useState(() => filters.search);
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const [queueNotice, setQueueNotice] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "recent",
    dir: "desc",
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const patchParams = useCallback(
    (patch: Record<string, string | number | null | undefined>) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(patch)) {
        if (value == null || value === "") {
          next.delete(key);
        } else {
          next.set(key, String(value));
        }
      }
      if ("filter" in patch) {
        const slug = patch.filter;
        if (slug == null || slug === "all") {
          next.delete("filter");
        } else if (slug === "submitted_unverified") {
          next.set("filter", "unverified");
        } else if (slug === "claude_escalated") {
          next.set("filter", "claude");
        } else if (typeof slug === "string") {
          next.set("filter", slug === "needs_action" ? "needs" : slug);
        }
      }
      onSearchParamsChange(next);
    },
    [searchParams, onSearchParamsChange],
  );

  const statusFilter = filters.filter;

  useEffect(() => {
    setSearchInput(filters.search);
  }, [filters.search]);

  useEffect(() => {
    if (debouncedSearch === filters.search) return;
    patchParams({ search: debouncedSearch || null, page: 1 });
  }, [debouncedSearch, filters.search, patchParams]);

  const handleApplyListAction = ({ action, title }: ApplyListActionInfo) => {
    const who = title?.trim() || "This job";
    setQueueNotice(
      action === "retry"
        ? `${who} was reset for another apply attempt. It no longer appears here because it is back in the apply queue — use Apply queue now or run applypilot apply.`
        : `${who} was returned to the apply queue. It no longer appears in this list until apply runs again — use Apply queue now or run applypilot apply.`,
    );
  };

  const querySearch = debouncedSearch.trim() || undefined;
  const queryOffset = (filters.page - 1) * filters.limit;

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const applicationsQueryKey = [
    "applications",
    statusFilter,
    querySearch,
    filters.page,
    filters.limit,
  ] as const;

  const { data, isPending, error, isFetching } = useQuery({
    queryKey: applicationsQueryKey,
    queryFn: () =>
      fetchApplications({
        limit: filters.limit,
        offset: queryOffset,
        include_failed: applicationsIncludeFailedForFilter(statusFilter),
        status: apiStatusForFilter(statusFilter),
        claude_escalated: statusFilter === "claude_escalated",
        needs_attention: apiNeedsAttentionForFilter(statusFilter),
        search: querySearch,
      }),
    refetchInterval: 15_000,
  });

  // Keep showing the last loaded page while refetching the same query key.
  // (Clearing on isFetching was wiping "All attempts" every 15s.)
  const applications = data?.applications ?? [];
  const total = data?.total ?? 0;
  const pages = total > 0 ? Math.ceil(total / filters.limit) : 0;
  const currentPage = filters.page;
  const pageStart = total === 0 ? 0 : (currentPage - 1) * filters.limit + 1;
  const pageEnd = total === 0 ? 0 : Math.min(currentPage * filters.limit, total);
  const listLoading = isPending || (isFetching && applications.length === 0);

  const manualRows = useMemo(
    () => (statusFilter === "all" ? applications.filter(needsHumanIntervention) : []),
    [applications, statusFilter],
  );

  const mainListRows = useMemo(() => {
    if (statusFilter === "all") {
      return applications.filter((a) => !needsHumanIntervention(a));
    }
    return applications;
  }, [applications, statusFilter]);

  const sortedMainRows = useMemo(() => {
    const mul = sort.dir === "asc" ? 1 : -1;
    const rows = [...mainListRows];
    rows.sort((a, b) => {
      switch (sort.key) {
        case "fit":
          return ((a.fit_score ?? -1) - (b.fit_score ?? -1)) * mul;
        case "attempts":
          return ((a.apply_attempts ?? 0) - (b.apply_attempts ?? 0)) * mul;
        case "duration":
          return ((a.apply_duration_ms ?? 0) - (b.apply_duration_ms ?? 0)) * mul;
        case "company":
          return (a.site ?? "").localeCompare(b.site ?? "") * mul;
        case "status":
          return (
            statusLabel(a.apply_status ?? "").localeCompare(statusLabel(b.apply_status ?? "")) *
            mul
          );
        case "recent":
        default: {
          const ta = applicationAttemptAt(a);
          const tb = applicationAttemptAt(b);
          return ((ta ? Date.parse(ta) : 0) - (tb ? Date.parse(tb) : 0)) * mul;
        }
      }
    });
    return rows;
  }, [mainListRows, sort]);

  const pinnedNeedsRows = useMemo(() => {
    if (statusFilter !== "all" || manualRows.length === 0) return [];
    return [...manualRows].sort((a, b) => {
      const ta = applicationAttemptAt(a);
      const tb = applicationAttemptAt(b);
      return (tb ? Date.parse(tb) : 0) - (ta ? Date.parse(ta) : 0);
    });
  }, [manualRows, statusFilter]);

  const displayRows = useMemo(
    () => (pinnedNeedsRows.length > 0 ? [...pinnedNeedsRows, ...sortedMainRows] : sortedMainRows),
    [pinnedNeedsRows, sortedMainRows],
  );

  const showPagination = pages > 1;

  const toggleSort = useCallback((key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: SORT_DEFAULT_DIR[key] },
    );
  }, []);

  const selected = useMemo(
    () => applications.find((a) => a.url === selectedUrl) ?? null,
    [applications, selectedUrl],
  );

  const pipeline = stats?.pipeline ?? {};
  const readyCount = stats?.ready_to_apply ?? pipeline.pending_apply ?? 0;
  const appliedCount = (pipeline.applied as number | undefined) ?? stats?.applied ?? 0;
  const failedCount = (pipeline.apply_errors as number | undefined) ?? 0;
  const submittedUnverifiedCount = (pipeline.submitted_unverified as number | undefined) ?? 0;
  const manualCount = (stats?.extra?.apply_manual as number | undefined) ?? 0;
  const allAttemptsCount = appliedCount + failedCount + submittedUnverifiedCount + manualCount;
  const needsActionCount = submittedUnverifiedCount + manualCount;
  const claudeEscalatedCount =
    (stats?.extra?.claude_escalated as number | undefined) ?? 0;

  useEffect(() => {
    if (isPending || pages === 0) return;
    if (filters.page > pages) {
      patchParams({ page: pages });
    }
  }, [filters.page, pages, isPending, patchParams]);

  useEffect(() => {
    if (applications.length === 0) {
      setSelectedUrl(null);
      return;
    }
    if (!selectedUrl || !applications.some((a) => a.url === selectedUrl)) {
      setSelectedUrl(applications[0]?.url ?? null);
    }
  }, [applications, selectedUrl]);

  const handleStatusChange = (next: ApplyStatusFilter) => {
    patchParams({ filter: next, page: 1 });
  };

  const filterChips: { key: ApplyStatusFilter; label: string; count?: number }[] = [
    { key: "all", label: "All", count: allAttemptsCount },
    { key: "applied", label: "Applied (all time)", count: appliedCount },
    { key: "failed", label: "Failed", count: failedCount },
    { key: "submitted_unverified", label: "Unverified", count: submittedUnverifiedCount },
    { key: "claude_escalated", label: "Escalated to Claude", count: claudeEscalatedCount },
    { key: "needs_action", label: "Needs help", count: needsActionCount },
  ];

  const panelCount =
    statusFilter === "all"
      ? allAttemptsCount
      : statusFilter === "applied"
        ? appliedCount
        : statusFilter === "failed"
          ? failedCount
          : statusFilter === "submitted_unverified"
            ? submittedUnverifiedCount
            : statusFilter === "claude_escalated"
              ? claudeEscalatedCount
              : statusFilter === "needs_action"
                ? needsActionCount
                : total;

  return (
    <PageCanvas wide className="apps-page">
      <div className="apps__hd">
        <div className="apps__hd-copy">
          <div className="apps__hd-kicker">Queue</div>
          <div className="apps__hd-line">
            {readyCount} jobs ready to apply · {needsActionCount} need your help
            {!isPending && total > 0 ? (
              <>
                {" "}
                · {total} in this view
              </>
            ) : null}
          </div>
        </div>
        <div className="apps__hd-actions">
          {showApplyControls ? (
            <>
              <button
                type="button"
                className="btn"
                disabled={!applyRun.isRunning}
                onClick={() => void applyRun.handleStop()}
              >
                Pause queue
              </button>
              <button
                type="button"
                className="btn btn--accent btn--lg"
                disabled={applyRun.isRunning || applyRun.starting}
                onClick={() => setApplyPlanOpen(true)}
              >
                {applyRun.starting ? "Starting…" : "Apply queue now"}
              </button>
            </>
          ) : (
            <button type="button" className="btn btn--ghost" onClick={() => handleStatusChange("needs_action")}>
              Review manual
            </button>
          )}
        </div>
      </div>

      {queueNotice ? (
        <div className="apps__notice" role="status">
          <p className="apps__notice-text">{queueNotice}</p>
          <div className="apps__notice-actions">
            {showApplyControls ? (
              <button
                type="button"
                className="btn btn--sm btn--accent"
                onClick={() => {
                  setQueueNotice(null);
                  setApplyPlanOpen(true);
                }}
              >
                Apply queue now
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              onClick={() => setQueueNotice(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <div className="apps">
        <div className="apps__list">
          <div className="apps__filterbar">
            {filterChips.map((chip) => {
              const on = statusFilter === chip.key;
              return (
                <button
                  key={chip.key}
                  type="button"
                  className={on ? "chip chip--on" : "chip"}
                  onClick={() => handleStatusChange(chip.key)}
                >
                  {chip.label}
                  {chip.count != null ? <span className="chip__count">{chip.count}</span> : null}
                </button>
              );
            })}
          </div>

          <div className="apps__controls apps__controls--compact" aria-label="Search and sort applications">
            <input
              className="apps__controls-search"
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search company or role…"
              aria-label="Search company or role"
            />
            <select
              className="apps__controls-sort"
              value={sort.key}
              aria-label="Sort by"
              onChange={(e) => {
                const key = e.target.value as SortKey;
                setSort({ key, dir: SORT_DEFAULT_DIR[key] });
              }}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div className="apps__ledger">
            <div className="apps__ledger-hd panel__head panel__head--inset">
              <div>
                <div className="panel__title">
                  {statusFilter === "failed"
                    ? "Failed"
                    : statusFilter === "submitted_unverified"
                      ? "Unverified"
                      : statusFilter === "needs_action"
                        ? "Needs help"
                        : statusFilter === "claude_escalated"
                          ? "Escalated to Claude"
                          : statusFilter === "applied"
                            ? "Applied"
                            : "All attempts"}
                </div>
                <div className="panel__sub">
                  {panelCount || "—"}{" "}
                  {statusFilter === "applied"
                    ? "verified submissions · all time"
                    : statusFilter === "all" && pinnedNeedsRows.length > 0
                      ? `${pinnedNeedsRows.length} need you · audit ledger`
                      : "matching · audit ledger"}
                </div>
              </div>
            </div>

            {error ? (
              <div className="apps__scroll apps__scroll--empty">
                <p className="panel__sub" style={{ padding: 16 }}>
                  {error instanceof Error ? error.message : "Error"}
                </p>
              </div>
            ) : displayRows.length === 0 && !listLoading ? (
              <div className="apps__scroll apps__scroll--empty">
                <p className="panel__sub" style={{ padding: 16 }}>
                  No applications match these filters.
                </p>
              </div>
            ) : (
              <div className="apps__table">
                <div className="apps__grid-viewport">
                  <div className="apps__grid-inner">
                    <div className="apps__thead" role="row">
                      <SortableTh label="Status" sortKey="status" sort={sort} onSort={toggleSort} />
                      <SortableTh
                        label="Role / Company"
                        sortKey="company"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <SortableTh
                        label="Fit"
                        sortKey="fit"
                        sort={sort}
                        onSort={toggleSort}
                        align="center"
                      />
                      <SortableTh label="When" sortKey="recent" sort={sort} onSort={toggleSort} />
                      <span className="apps__th">Outcome</span>
                      <SortableTh
                        label="Tries"
                        sortKey="attempts"
                        sort={sort}
                        onSort={toggleSort}
                        align="center"
                      />
                      <span className="apps__th apps__th--right">Actions</span>
                    </div>
                    <VirtualScroll
                      scrollRef={scrollRef}
                      className="apps__scroll"
                      items={displayRows}
                      getItemKey={(app) => app.url}
                      estimateSize={APP_ROW_PX}
                      overscan={12}
                    >
                      {(app) => (
                        <AppRow
                          app={app}
                          manual={needsHumanIntervention(app)}
                          selected={selectedUrl === app.url}
                          onSelect={() => setSelectedUrl(app.url)}
                          onApplyListAction={handleApplyListAction}
                        />
                      )}
                    </VirtualScroll>
                  </div>
                </div>
              </div>
            )}

            {showPagination ? (
              <div
                className="jobs__pager apps__pager apps__pager--foot"
                aria-label="Applications list pagination"
              >
                <label className="control jobs__pager-size">
                  <span className="control__label">Per page</span>
                  <select
                    className="control__input"
                    value={filters.limit}
                    onChange={(e) =>
                      patchParams({ limit: normalizePageSize(Number(e.target.value)), page: 1 })
                    }
                  >
                    {PAGE_SIZES.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="jobs__pager-meta panel__sub">
                  {listLoading ? (
                    "Loading…"
                  ) : (
                    <>
                      Showing <strong>{pageStart}</strong>–<strong>{pageEnd}</strong> of{" "}
                      <strong>{total}</strong>
                      {" · "}
                      page <strong>{currentPage}</strong> of <strong>{pages}</strong>
                    </>
                  )}
                </p>
                <div className="jobs__pager-actions">
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={currentPage <= 1 || listLoading}
                    onClick={() => patchParams({ page: currentPage - 1 })}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={currentPage >= pages || listLoading}
                    onClick={() => patchParams({ page: currentPage + 1 })}
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="apps__detail">
          <ApplicationDetailPanel app={selected} onApplyListAction={handleApplyListAction} />
        </div>
      </div>

      {showApplyControls ? (
        <ApplyRunPlanModal
          open={applyPlanOpen}
          settings={applyRun.applySettings}
          readyCount={stats?.ready_to_apply ?? readyCount}
          onCancel={() => setApplyPlanOpen(false)}
          onConfirm={() => {
            setApplyPlanOpen(false);
            void applyRun.handleStart();
          }}
        />
      ) : null}
    </PageCanvas>
  );
}

function AppRow({
  app,
  manual = false,
  selected,
  onSelect,
  onApplyListAction,
}: {
  app: import("../api").Application;
  manual?: boolean;
  selected: boolean;
  onSelect: () => void;
  onApplyListAction?: (info: ApplyListActionInfo) => void;
}) {
  const status = app.apply_status ?? "unknown";
  const label = manual
    ? "Manual"
    : isClaudeEscalated(app)
      ? "Claude queue"
      : statusLabel(status);
  const whenIso = applicationAttemptAt(app);
  const reason = applicationReasonLine(app);
  const reasonTone = applicationReasonTone(manual ? "manual" : status);

  const fit = app.fit_score;
  const company = companyLabelFromSite(app.site);
  const initials = companyInitials(company === "—" ? (app.title ?? "?") : company);

  return (
    <div
      className={
        selected
          ? manual
            ? "app-row app-row--selected app-row--needs"
            : "app-row app-row--selected"
          : manual
            ? "app-row app-row--needs"
            : "app-row"
      }
      onClick={onSelect}
    >
      <span className={statusbarClass(label)}>{label}</span>
      <button type="button" className="app-row__main app-row__select" onClick={onSelect}>
        <div className="app-row__title-line">
          <span className="app-row__logo" aria-hidden>
            {initials}
          </span>
          <span className="app-row__title">{app.title ?? "Untitled"}</span>
        </div>
        <div className="app-row__company">{company}</div>
      </button>
      <div className={fit != null && fit >= 8 ? "app-row__fit app-row__fit--hi" : "app-row__fit"}>
        {fit != null ? fit : "—"}
      </div>
      <div className="app-row__when">
        <span className="app-row__when-cap">{applicationDateCaption(app)}</span>
        <span className="app-row__when-val">{formatWhen(whenIso)}</span>
      </div>
      <div className="app-row__outcome">
        {reason ? (
          <div
            className={`app-row__reason app-row__reason--${reasonTone}`}
            title={app.apply_error ?? undefined}
          >
            {reason}
          </div>
        ) : (
          <div className="app-row__reason app-row__reason--muted">—</div>
        )}
      </div>
      <div className="app-row__tries">{app.apply_attempts ?? 0}</div>
      <div className="app-row__action-col" onClick={(e) => e.stopPropagation()}>
        <ApplicationRowActions
          app={app}
          layout="row"
          onApplyListAction={onApplyListAction}
        />
        {manual && app.url ? (
          <a
            className="btn btn--sm"
            href={app.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            Open job
          </a>
        ) : null}
      </div>
    </div>
  );
}

function SortableTh({
  label,
  sortKey,
  sort,
  onSort,
  align,
}: {
  label: string;
  sortKey: SortKey;
  sort: { key: SortKey; dir: SortDir };
  onSort: (key: SortKey) => void;
  align?: "center";
}) {
  const active = sort.key === sortKey;
  const cls = [
    "apps__th",
    "apps__th--btn",
    active ? "apps__th--sorted" : "",
    align === "center" ? "apps__th--center" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" className={cls} onClick={() => onSort(sortKey)}>
      {label}
      <span className="apps__th-caret" aria-hidden>
        {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
      </span>
    </button>
  );
}
