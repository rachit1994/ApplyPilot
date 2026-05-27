import { useQuery } from "@tanstack/react-query";
import { fetchSourceStats, type SourceStats, type Stats } from "../api";
import { isPriorityBoardName, sortByPriorityName } from "../utils/sitePriority";
import { PriorityBoardsBanner } from "./PriorityBoardsBanner";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

type Props = {
  stats: Stats | undefined;
  isLoading?: boolean;
};

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="py-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-4">{label}</p>
        <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink">
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

function SkeletonCard() {
  return (
    <Card>
      <CardContent className="py-3">
        <div className="skeleton h-3 w-16" />
        <div className="skeleton mt-2 h-8 w-12" />
      </CardContent>
    </Card>
  );
}

export function StatsRow({ stats, isLoading }: Props) {
  const { data: sourceStats } = useQuery({
    queryKey: ["source-stats", 7],
    queryFn: () => fetchSourceStats(7),
  });

  if (isLoading || !stats) {
    return (
      <section className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
        <Card>
          <CardContent className="py-3">
            <div className="skeleton h-3 w-24" />
            <div className="mt-2 flex flex-wrap gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="skeleton h-6 w-20 rounded-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      </section>
    );
  }

  const cards = [
    { label: "Total jobs", value: String(stats.total) },
    { label: "Scored", value: String(stats.scored) },
    { label: "Enriched", value: String(stats.with_description) },
    { label: "Tailored", value: String(stats.tailored) },
    { label: "Ready", value: String(stats.ready_to_apply) },
    { label: "Applied", value: String(stats.applied) },
  ];

  const topSites = sortByPriorityName([...(stats.by_site ?? [])]).slice(0, 8);
  const sortedSourceStats = sortByPriorityName(sourceStats ?? []);

  return (
    <section className="space-y-3">
      <PriorityBoardsBanner
        priorityBoards={stats.priority_boards}
        applyQueueOrder={stats.apply_queue_order}
      />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((c) => (
          <StatCard key={c.label} label={c.label} value={c.value} />
        ))}
      </div>

      {(stats.score_buckets?.length ?? 0) > 0 && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle>Fit score distribution</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="flex gap-2">
              {stats.score_buckets!.map((b) => {
                const total =
                  stats.score_buckets!.reduce((s, x) => s + x.count, 0) || 1;
                const pct = Math.round((b.count / total) * 100);
                return (
                  <div
                    key={b.bucket}
                    className="flex min-w-0 flex-1 flex-col gap-1"
                    title={`${b.bucket}: ${b.count} jobs (${pct}%)`}
                  >
                    <div className="h-2 overflow-hidden rounded-full bg-panel-muted">
                      <div
                        className="h-full rounded-full bg-accent/80"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="truncate text-[10px] text-ink-4">
                      {b.bucket} · {b.count}
                    </span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {topSites.length > 0 && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle>Jobs by source</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="flex flex-wrap gap-2">
              {topSites.map((row) => (
                <Badge
                  key={row.site ?? "unknown"}
                  variant={isPriorityBoardName(row.site) ? "default" : "secondary"}
                  className="normal-case"
                >
                  <span className="max-w-[120px] truncate">{row.site ?? "Unknown"}</span>
                  <span className="font-mono text-ink-4">{row.count}</span>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {sortedSourceStats.length > 0 && (
        <SourceStatsCard rows={sortedSourceStats.slice(0, 8)} />
      )}
    </section>
  );
}

function SourceStatsCard({ rows }: { rows: SourceStats[] }) {
  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle>Sources this week</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-ink-4">
              <tr>
                <th className="py-1 font-medium">Source</th>
                <th className="py-1 text-right font-medium">Discovered</th>
                <th className="py-1 text-right font-medium">Passed</th>
                <th className="py-1 text-right font-medium">Score ≥7</th>
                <th className="py-1 text-right font-medium">Tailored</th>
                <th className="py-1 text-right font-medium">Efficiency</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.source} className="border-t border-panel-border">
                  <td className="max-w-[160px] truncate py-2 text-ink">
                    <span className="inline-flex items-center gap-2">
                      {row.source}
                      {isPriorityBoardName(row.source) ? (
                        <Badge variant="default" className="normal-case text-[10px]">
                          Priority
                        </Badge>
                      ) : null}
                    </span>
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-ink-3">
                    {row.discovered}
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-ink-3">
                    {row.passed_filter}
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-ink-3">
                    {row.scored_ge7}
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-ink-3">
                    {row.tailored}
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-accent">
                    {Math.round(row.efficiency * 100)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
