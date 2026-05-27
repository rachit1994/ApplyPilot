import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApplications, fetchStats, type Application } from "../api";
import { ApplicationDetailPanel } from "./ApplicationDetailPanel";
import {
  apiStatusForFilter,
  applicationSummaryLine,
  applyStatusFilterFromUrl,
  formatWhen,
  needsHumanIntervention,
  statusChipClass,
  statusLabel,
  type ApplyStatusFilter,
} from "../utils/applicationAudit";

type Props = {
  initialFilter?: string | null;
  onFilterChange?: (filter: ApplyStatusFilter) => void;
};

export function AppliedApplicationsPage({ initialFilter, onFilterChange }: Props) {
  const [statusFilter, setStatusFilter] = useState<ApplyStatusFilter>(() =>
    applyStatusFilterFromUrl(initialFilter ?? null),
  );
  const [search, setSearch] = useState("");
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const [hasSnapshotOnly, setHasSnapshotOnly] = useState(false);

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
    if (hasSnapshotOnly) {
      list = list.filter(
        (a) =>
          (a.form_filled?.field_count ?? a.form_filled?.fields?.length ?? 0) > 0 ||
          Boolean(a.apply_log_path),
      );
    }
    return list;
  }, [data?.applications, hasSnapshotOnly, statusFilter]);

  const selected = useMemo(
    () => applications.find((a) => a.url === selectedUrl) ?? applications[0] ?? null,
    [applications, selectedUrl],
  );

  const pipeline = stats?.pipeline ?? {};

  useEffect(() => {
    setStatusFilter(applyStatusFilterFromUrl(initialFilter ?? null));
  }, [initialFilter]);

  const handleStatusChange = (next: ApplyStatusFilter) => {
    setStatusFilter(next);
    onFilterChange?.(next);
  };

  return (
    <div className="flex h-[min(72vh,calc(100vh-8rem))] min-h-[420px] flex-col gap-4">
      <header className="shrink-0 space-y-3">
        <div>
          <h2 className="font-display text-xl text-ink">Applications</h2>
          <p className="mt-1 text-sm text-ink-3">
            Every apply attempt — fields filled, failure reasons, and submit proof.
          </p>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-ink-3">
          <StatPill label="Applied" value={stats?.applied} />
          <StatPill label="Needs verification" value={pipeline.submitted_unverified} warn />
          <StatPill label="Failed" value={pipeline.apply_errors} bad />
          <StatPill label="Manual" value={stats?.extra?.apply_manual} />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-3">
            Status
            <select
              value={statusFilter}
              onChange={(e) => handleStatusChange(e.target.value as ApplyStatusFilter)}
              className="mt-1 block rounded border border-panel-border bg-canvas px-2 py-1.5 text-sm text-ink"
            >
              <option value="all">All outcomes</option>
              <option value="needs_action">Needs action</option>
              <option value="applied">Applied</option>
              <option value="submitted_unverified">Needs verification</option>
              <option value="failed">Failed</option>
              <option value="manual">Manual</option>
            </select>
          </label>
          <label className="min-w-[12rem] flex-1 text-xs text-ink-3">
            Search title
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Company or role…"
              className="mt-1 w-full rounded border border-panel-border bg-canvas px-2 py-1.5 text-sm text-ink"
            />
          </label>
          <label className="flex items-center gap-2 pb-1.5 text-xs text-ink-3">
            <input
              type="checkbox"
              checked={hasSnapshotOnly}
              onChange={(e) => setHasSnapshotOnly(e.target.checked)}
            />
            Has apply log only
          </label>
        </div>
      </header>

      {isLoading ? <p className="text-sm text-ink-3">Loading applications…</p> : null}
      {error ? (
        <p className="text-sm text-bad">{error instanceof Error ? error.message : "Error"}</p>
      ) : null}

      {!isLoading && applications.length === 0 ? (
        <p className="rounded-card border border-panel-border bg-panel p-6 text-sm text-ink-3">
          No applications match these filters. Run apply from the Apply page or check failed
          attempts.
        </p>
      ) : null}

      {applications.length > 0 ? (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(240px,320px)_1fr]">
          <ul className="scroll-thin min-h-0 space-y-1 overflow-y-auto rounded-card border border-panel-border bg-panel p-2">
            {applications.map((app) => (
              <ApplicationListItem
                key={app.url}
                app={app}
                selected={selected?.url === app.url}
                onSelect={() => setSelectedUrl(app.url)}
              />
            ))}
          </ul>
          <ApplicationDetailPanel app={selected} />
        </div>
      ) : null}
    </div>
  );
}

function ApplicationListItem({
  app,
  selected,
  onSelect,
}: {
  app: Application;
  selected: boolean;
  onSelect: () => void;
}) {
  const status = app.apply_status ?? "unknown";
  const summary = applicationSummaryLine(app);

  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors ${
          selected ? "bg-accent/10 ring-1 ring-accent/40" : "hover:bg-panel-elevated"
        }`}
      >
        <div className="flex items-start gap-2">
          <span
            className={`mt-0.5 shrink-0 rounded-chip px-1.5 py-0.5 text-[9px] font-medium uppercase ${statusChipClass(status)}`}
          >
            {statusLabel(status)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">{app.title ?? "Untitled"}</p>
            <p className="mt-0.5 text-[10px] text-ink-4">
              {app.site ?? "—"}
              {app.fit_score != null ? ` · ${app.fit_score}` : ""}
              {app.applied_at ? ` · ${formatWhen(app.applied_at)}` : ""}
            </p>
            {summary ? (
              <p className="mt-1 line-clamp-2 text-[10px] text-warn">{summary}</p>
            ) : null}
          </div>
        </div>
      </button>
    </li>
  );
}

function StatPill({
  label,
  value,
  warn,
  bad,
}: {
  label: string;
  value?: number | string;
  warn?: boolean;
  bad?: boolean;
}) {
  const tone = bad ? "text-bad" : warn ? "text-warn" : "text-ink";
  return (
    <span>
      {label}: <strong className={tone}>{value ?? "—"}</strong>
    </span>
  );
}
