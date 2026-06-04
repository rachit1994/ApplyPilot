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
import { statusbarClass } from "../utils/statusbar";

const APP_ROW_PX = 72;
const PAGE_SIZES = [25, 50, 100] as const;

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

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["applications", statusFilter, querySearch, filters.page, filters.limit],
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

  const pageAligned = isLoading || !isFetching;
  const applications = pageAligned ? (data?.applications ?? []) : [];
  const total = pageAligned ? (data?.total ?? 0) : 0;
  const pages = total > 0 ? Math.ceil(total / filters.limit) : 0;
  const currentPage = filters.page;
  const pageStart = total === 0 ? 0 : (currentPage - 1) * filters.limit + 1;
  const pageEnd = total === 0 ? 0 : Math.min(currentPage * filters.limit, total);
  const listLoading = isLoading || (isFetching && !pageAligned);

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
    if (!pageAligned || pages === 0) return;
    if (filters.page > pages) {
      patchParams({ page: pages });
    }
  }, [filters.page, pages, pageAligned, patchParams]);

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
    <PageCanvas>
      <div className="apps__hd">
        <div className="apps__hd-copy">
          <div className="apps__hd-kicker">Queue</div>
          <div className="apps__hd-line">
            {readyCount} jobs ready to apply · {needsActionCount} need your help
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
        <label className="control">
          <span className="control__label">Search</span>
          <input
            className="control__input"
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Company or role…"
          />
        </label>
      </div>

      <div className="apps">
        <div className="apps__list">
          {manualRows.length > 0 ? (
            <div className="errors-band">
              <div className="errors-band__hd">
                <span className="errors-band__title">Need your apply</span>
                <span className="errors-band__count">{manualRows.length}</span>
              </div>
              {manualRows.map((app) => (
                <AppRow
                  key={app.url}
                  app={app}
                  manual
                  selected={selectedUrl === app.url}
                  onSelect={() => setSelectedUrl(app.url)}
                  onApplyListAction={handleApplyListAction}
                />
              ))}
            </div>
          ) : null}

          <div className="panel apps__panel">
            <div className="panel__head panel__head--inset">
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
                    : "matching · audit ledger"}
                </div>
              </div>
            </div>

            <div className="jobs__pager apps__pager" aria-label="Applications list pagination">
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
                ) : total === 0 ? (
                  "No rows match these filters."
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
                  disabled={pages === 0 || currentPage >= pages || listLoading}
                  onClick={() => patchParams({ page: currentPage + 1 })}
                >
                  Next
                </button>
              </div>
            </div>

            {error ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                {error instanceof Error ? error.message : "Error"}
              </p>
            ) : mainListRows.length === 0 && !listLoading ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                No applications match these filters.
              </p>
            ) : (
              <div className="apps__scroll">
                <VirtualScroll
                  scrollRef={scrollRef}
                  className="panel__body panel__body--tight"
                  items={mainListRows}
                  getItemKey={(app) => app.url}
                  estimateSize={APP_ROW_PX}
                  overscan={12}
                >
                  {(app) => (
                    <AppRow
                      app={app}
                      selected={selectedUrl === app.url}
                      onSelect={() => setSelectedUrl(app.url)}
                      onApplyListAction={handleApplyListAction}
                    />
                  )}
                </VirtualScroll>
              </div>
            )}
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

  return (
    <div className={selected ? "app-row app-row--selected" : "app-row"}>
      <span className={statusbarClass(label)}>{label}</span>
      <button type="button" className="app-row__main app-row__select" onClick={onSelect}>
        <div className="app-row__title">{app.title ?? "Untitled"}</div>
        <div className="app-row__company">{app.site ?? "—"}</div>
      </button>
      <div className="app-row__meta">
        <div className="app-row__date">
          <span className="app-row__date-label">{applicationDateCaption(app)}</span>
          <span className="app-row__date-value">{formatWhen(whenIso)}</span>
        </div>
        {reason ? (
          <div className={`app-row__reason app-row__reason--${reasonTone}`} title={app.apply_error ?? undefined}>
            {reason}
          </div>
        ) : null}
      </div>
      <div className="app-row__action-col">
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
      <button type="button" className="chev" onClick={onSelect} aria-label="Open details">
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" aria-hidden>
          <path d="m5 3 4 4-4 4" />
        </svg>
      </button>
    </div>
  );
}
