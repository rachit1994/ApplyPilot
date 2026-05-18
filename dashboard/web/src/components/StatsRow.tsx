import type { Stats } from "../api";

type Props = {
  stats: Stats | undefined;
  isLoading?: boolean;
};

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-3 py-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">{label}</p>
      <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-zinc-100">
        {value}
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="panel px-3 py-3">
      <div className="skeleton h-3 w-16" />
      <div className="skeleton mt-2 h-8 w-12" />
    </div>
  );
}

export function StatsRow({ stats, isLoading }: Props) {
  if (isLoading || !stats) {
    return (
      <section className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
        <div className="panel p-3">
          <div className="skeleton h-3 w-24" />
          <div className="mt-2 flex flex-wrap gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-6 w-20 rounded-full" />
            ))}
          </div>
        </div>
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

  const topSites = (stats.by_site ?? []).slice(0, 8);

  return (
    <section className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((c) => (
          <StatCard key={c.label} label={c.label} value={c.value} />
        ))}
      </div>

      {(stats.score_buckets?.length ?? 0) > 0 && (
        <div className="panel p-3">
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
            Fit score distribution
          </h3>
          <div className="mt-2 flex gap-2">
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
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-sky-500/80"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="truncate text-[10px] text-zinc-500">
                    {b.bucket} · {b.count}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {topSites.length > 0 && (
        <div className="panel p-3">
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
            Jobs by source
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {topSites.map((row) => (
              <span
                key={row.site ?? "unknown"}
                className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700/80 bg-zinc-900/60 px-2.5 py-1 text-xs"
              >
                <span className="max-w-[120px] truncate text-zinc-300">
                  {row.site ?? "Unknown"}
                </span>
                <span className="font-mono text-zinc-500">{row.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
