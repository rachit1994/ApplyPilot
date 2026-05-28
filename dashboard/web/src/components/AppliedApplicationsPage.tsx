import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApplications, fetchStats } from "../api";
import { useApplyRun } from "../hooks/useApplyRun";
import { ApplicationDetailPanel } from "./ApplicationDetailPanel";
import { PageCanvas } from "./layout/PageCanvas";
import { VirtualScroll } from "./VirtualScroll";
import {
  apiStatusForFilter,
  applicationSummaryLine,
  applyStatusFilterFromUrl,
  formatWhen,
  needsHumanIntervention,
  statusLabel,
  type ApplyStatusFilter,
} from "../utils/applicationAudit";
import { statusbarClass } from "../utils/statusbar";

const APP_ROW_PX = 52;

type Props = {
  initialFilter?: string | null;
  onFilterChange?: (filter: ApplyStatusFilter) => void;
  showApplyControls?: boolean;
};

export function AppliedApplicationsPage({
  initialFilter,
  onFilterChange,
  showApplyControls = false,
}: Props) {
  const applyRun = useApplyRun();
  const [statusFilter, setStatusFilter] = useState<ApplyStatusFilter>(() =>
    applyStatusFilterFromUrl(initialFilter ?? null),
  );
  const [search, setSearch] = useState("");
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["applications", statusFilter, search],
    queryFn: () =>
      fetchApplications({
        limit: 300,
        include_failed: true,
        status: apiStatusForFilter(statusFilter),
        search: search.trim() || undefined,
      }),
    refetchInterval: 15_000,
  });

  const applications = useMemo(() => {
    let list = data?.applications ?? [];
    if (statusFilter === "needs_action") {
      list = list.filter(needsHumanIntervention);
    }
    return list;
  }, [data?.applications, statusFilter]);

  const manualRows = useMemo(
    () => applications.filter(needsHumanIntervention),
    [applications],
  );

  const appliedRows = useMemo(
    () => applications.filter((a) => !needsHumanIntervention(a)),
    [applications],
  );

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

  useEffect(() => {
    setStatusFilter(applyStatusFilterFromUrl(initialFilter ?? null));
  }, [initialFilter]);

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
    setStatusFilter(next);
    onFilterChange?.(next);
  };

  const filterChips: { key: ApplyStatusFilter; label: string; count?: number }[] = [
    { key: "all", label: "All", count: allAttemptsCount },
    { key: "applied", label: "Applied", count: appliedCount },
    { key: "failed", label: "Failed", count: failedCount },
    { key: "submitted_unverified", label: "Unverified", count: submittedUnverifiedCount },
    { key: "needs_action", label: "Needs help", count: needsActionCount },
  ];

  return (
    <PageCanvas>
      <div className="apps__hd">
        <div>
          <div className="section-title" style={{ marginBottom: 4 }}>
            Queue
          </div>
          <div
            style={{
              fontFamily: "var(--display)",
              fontSize: 15,
              fontWeight: 600,
              color: "var(--ink)",
              letterSpacing: "-0.015em",
            }}
          >
            {readyCount} jobs ready to apply · {manualRows.length} need your help
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
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
                onClick={() => void applyRun.handleStart()}
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
        <label className="control" style={{ marginLeft: "auto", minWidth: 200 }}>
          <span className="control__label">Search</span>
          <input
            className="control__input"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Company or role…"
          />
        </label>
      </div>

      <div className="apps">
        <div className="apps__list">
          {manualRows.length > 0 && statusFilter !== "applied" ? (
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
                        : statusFilter === "applied"
                          ? "Applied"
                          : "All attempts"}
                </div>
                <div className="panel__sub">
                  {(statusFilter === "all"
                    ? allAttemptsCount
                    : statusFilter === "applied"
                      ? appliedCount
                      : statusFilter === "failed"
                        ? failedCount
                        : statusFilter === "submitted_unverified"
                          ? submittedUnverifiedCount
                          : needsActionCount) || "—"}{" "}
                  {statusFilter === "applied" ? "submissions" : "attempts"} · audit ledger
                </div>
              </div>
            </div>
            {isLoading ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                Loading…
              </p>
            ) : error ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                {error instanceof Error ? error.message : "Error"}
              </p>
            ) : appliedRows.length === 0 ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                No applications match these filters.
              </p>
            ) : (
              <div className="apps__scroll">
                <VirtualScroll
                  scrollRef={scrollRef}
                  className="panel__body panel__body--tight"
                  items={appliedRows}
                  getItemKey={(app) => app.url}
                  estimateSize={APP_ROW_PX}
                  overscan={12}
                >
                  {(app) => (
                    <AppRow
                      app={app}
                      selected={selectedUrl === app.url}
                      onSelect={() => setSelectedUrl(app.url)}
                    />
                  )}
                </VirtualScroll>
              </div>
            )}
          </div>
        </div>

        <div className="apps__detail">
          {selected ? (
            <div className="panel apps__detailPanel">
              <ApplicationDetailPanel app={selected} />
            </div>
          ) : (
            <div className="panel apps__detailPanel">
              <div className="panel__head panel__head--inset">
                <div>
                  <div className="panel__title">Details</div>
                  <div className="panel__sub">Select an application to see its audit ledger.</div>
                </div>
              </div>
              <div className="panel__body">
                <p className="panel__sub">No selection.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </PageCanvas>
  );
}

function AppRow({
  app,
  manual = false,
  selected,
  onSelect,
}: {
  app: import("../api").Application;
  manual?: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const status = app.apply_status ?? "unknown";
  const label = manual ? "Manual" : statusLabel(status);
  const reason = applicationSummaryLine(app) || app.apply_error || "";

  return (
    <div className={selected ? "app-row app-row--selected" : "app-row"}>
      <span className={statusbarClass(label)}>{label}</span>
      <button type="button" className="app-row__main" onClick={onSelect} style={{ textAlign: "left" }}>
        <div className="app-row__title">{app.title ?? "Untitled"}</div>
        <div className="app-row__company">
          {app.site ?? "—"}
          {app.applied_at ? ` · ${formatWhen(app.applied_at)}` : ""}
        </div>
      </button>
      {manual ? (
        <>
          <div className="app-row__reason">{reason || "Needs review"}</div>
          {app.url ? (
            <a className="btn btn--sm btn--accent" href={app.url} target="_blank" rel="noreferrer">
              Apply now
            </a>
          ) : (
            <button type="button" className="btn btn--sm btn--accent">
              Apply now
            </button>
          )}
        </>
      ) : (
        <div className="app-row__date">{app.applied_at ? formatWhen(app.applied_at) : "—"}</div>
      )}
      <button type="button" className="chev" onClick={onSelect} aria-label="Open details">
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" aria-hidden>
          <path d="m5 3 4 4-4 4" />
        </svg>
      </button>
    </div>
  );
}
