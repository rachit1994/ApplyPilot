import type { RunEvent } from "../../api";
import {
  isPriorityBoardName,
  PRIORITY_BOARD_NAMES,
  sortByPriorityName,
} from "../../utils/sitePriority";
import { Badge } from "../ui/badge";

type SourceRow = {
  source: string;
  status: string;
  new_jobs?: number;
  index?: number;
  total?: number;
  detail?: string;
  priority?: boolean;
};

export function DiscoverSourcePanel({ events }: { events: RunEvent[] }) {
  const bySource = new Map<string, SourceRow>();

  for (const e of events) {
    if (e.event_type !== "source_progress") continue;
    const p = (e.payload ?? {}) as SourceRow;
    const source = p.source ?? "unknown";
    bySource.set(source, {
      source,
      status: p.status ?? "?",
      new_jobs: p.new_jobs,
      index: p.index,
      total: p.total,
      detail: p.detail ?? e.message ?? undefined,
      priority: Boolean(p.priority) || isPriorityBoardName(source),
    });
  }

  const rows = sortByPriorityName([...bySource.values()]);

  if (rows.length === 0) {
    return (
      <section className="rounded-card border border-panel-border bg-panel p-4">
        <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
          Discover sources
        </h3>
        <p className="mt-2 text-xs text-ink-3">
          Smart extract runs boards in priority order. These run first:
        </p>
        <ul className="mt-3 flex flex-wrap gap-2">
          {PRIORITY_BOARD_NAMES.map((name) => (
            <li key={name} className="list-none">
              <Badge variant="default" className="normal-case">
                {name}
              </Badge>
            </li>
          ))}
        </ul>
        <p className="mt-2 font-mono text-[11px] text-ink-4">
          Start a discover run to see per-board progress here.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-card border border-panel-border bg-panel p-4">
      <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
        Discover sources
      </h3>
      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <li
            key={row.source}
            className="flex flex-wrap items-center justify-between gap-2 rounded border border-panel-border bg-panel-elevated px-3 py-2 text-xs"
          >
            <span className="flex items-center gap-2 font-mono text-ink">
              {row.source}
              {row.priority ? (
                <Badge variant="default" className="normal-case text-[10px]">
                  Priority
                </Badge>
              ) : null}
            </span>
            <span
              className={
                row.status.startsWith("error")
                  ? "text-bad"
                  : row.status === "ok"
                    ? "text-good"
                    : "text-ink-3"
              }
            >
              {row.status}
            </span>
            {row.new_jobs != null && row.new_jobs > 0 ? (
              <span className="text-accent">+{row.new_jobs} new</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
