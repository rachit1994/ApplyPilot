import { useEffect, useState } from "react";
import type { Job } from "../api";

type Props = {
  jobs: Job[];
  recentJobs: Job[];
  minScoreFilter: number;
  onMinScoreChange: (n: number) => void;
  search: string;
  onSearchChange: (q: string) => void;
  total: number;
  isLoading?: boolean;
};

function scoreBadge(score: number | null) {
  if (score == null) return <span className="text-zinc-600">—</span>;
  const color =
    score >= 8 ? "text-emerald-400" : score >= 6 ? "text-amber-300" : "text-zinc-400";
  return <span className={`font-mono font-semibold tabular-nums ${color}`}>{score}</span>;
}

function TableSkeleton() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, i) => (
        <tr key={i} className="border-t border-zinc-800/50">
          <td className="px-4 py-3">
            <div className="skeleton h-4 w-6" />
          </td>
          <td className="px-4 py-3">
            <div className="skeleton h-4 w-full max-w-[200px]" />
          </td>
          <td className="px-4 py-3">
            <div className="skeleton h-4 w-16" />
          </td>
        </tr>
      ))}
    </>
  );
}

export function JobsTable({
  jobs,
  recentJobs,
  minScoreFilter,
  onMinScoreChange,
  search,
  onSearchChange,
  total,
  isLoading,
}: Props) {
  const [debouncedSearch, setDebouncedSearch] = useState(search);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  const showEmpty = !isLoading && jobs.length === 0;

  return (
    <section className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <header className="panel-header flex-wrap">
        <h2 className="panel-title">Jobs</h2>
        <span className="text-[10px] text-zinc-600">{total} matching</span>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800/80 px-4 py-3">
        <input
          type="search"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search title or company…"
          className="min-w-[12rem] flex-1 rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30"
        />
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          Min score
          <select
            value={minScoreFilter}
            onChange={(e) => onMinScoreChange(Number(e.target.value))}
            className="rounded-lg border border-zinc-700 bg-zinc-900/80 px-2 py-1.5 text-sm text-zinc-200"
          >
            {[0, 5, 6, 7, 8, 9].map((n) => (
              <option key={n} value={n}>
                {n === 0 ? "Any" : `≥ ${n}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      {recentJobs.length > 0 && (
        <div className="border-b border-zinc-800/50 px-4 py-2">
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-zinc-600">
            Recent activity
          </p>
          <div className="scroll-thin max-h-24 space-y-1 overflow-y-auto text-xs">
            {recentJobs.slice(0, 6).map((j) => (
              <div key={j.url} className="flex justify-between gap-2">
                <span className="truncate text-zinc-400">{j.title ?? j.url}</span>
                {scoreBadge(j.fit_score)}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 z-10 bg-zinc-950/95 text-[10px] font-medium uppercase tracking-wide text-zinc-500 backdrop-blur">
            <tr className="border-b border-zinc-800">
              <th className="px-4 py-2.5 w-14">Score</th>
              <th className="px-4 py-2.5">Role</th>
              <th className="px-4 py-2.5 w-28">Source</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <TableSkeleton />}
            {!isLoading &&
              jobs.map((j) => (
                <tr
                  key={j.url}
                  className="border-t border-zinc-800/60 transition-colors hover:bg-zinc-800/30"
                >
                  <td className="px-4 py-2.5">{scoreBadge(j.fit_score)}</td>
                  <td className="max-w-[240px] px-4 py-2.5">
                    <a
                      href={j.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block truncate text-blue-400 hover:text-blue-300 hover:underline"
                      title={j.score_reasoning ?? j.title ?? j.url}
                    >
                      {j.title ?? "Untitled"}
                    </a>
                    {j.location && (
                      <p className="truncate text-[10px] text-zinc-600">{j.location}</p>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-zinc-500">{j.site ?? "—"}</td>
                </tr>
              ))}
          </tbody>
        </table>

        {showEmpty && (
          <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
            <p className="text-sm font-medium text-zinc-400">No jobs match</p>
            <p className="mt-1 max-w-xs text-xs text-zinc-600">
              {debouncedSearch
                ? "Try a different search or lower the minimum score."
                : "Run the pipeline to discover and score roles."}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
