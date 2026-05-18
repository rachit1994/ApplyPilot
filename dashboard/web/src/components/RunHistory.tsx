import { useQuery } from "@tanstack/react-query";
import { fetchRuns, type Run } from "../api";
import { formatDuration, formatTime, runDuration } from "../utils/format";

type Props = {
  activeRunId: string | null;
  onSelectRun?: (run: Run) => void;
};

function statusDot(status: string): string {
  switch (status) {
    case "running":
      return "bg-emerald-400";
    case "completed":
      return "bg-blue-400";
    case "failed":
      return "bg-red-400";
    case "stopped":
      return "bg-zinc-400";
    default:
      return "bg-zinc-600";
  }
}

export function RunHistory({ activeRunId, onSelectRun }: Props) {
  const { data: runs, isLoading, isError } = useQuery({
    queryKey: ["runs"],
    queryFn: fetchRuns,
    refetchInterval: 8_000,
  });

  const list = runs ?? [];

  return (
    <section className="panel flex min-h-0 flex-1 flex-col">
      <header className="panel-header shrink-0">
        <h2 className="panel-title">Run history</h2>
        <span className="text-[10px] text-zinc-600">{list.length}</span>
      </header>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading && (
          <ul className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <li key={i} className="skeleton h-14 rounded-lg" />
            ))}
          </ul>
        )}

        {isError && (
          <p className="px-2 py-4 text-center text-xs text-red-400">Could not load runs</p>
        )}

        {!isLoading && !isError && list.length === 0 && (
          <p className="px-2 py-6 text-center text-xs text-zinc-500">No runs yet</p>
        )}

        {!isLoading && list.length > 0 && (
          <ul className="space-y-1">
            {list.map((run) => {
              const selected = run.id === activeRunId;
              const dur = runDuration(run);
              return (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => onSelectRun?.(run)}
                    className={`w-full rounded-lg px-2.5 py-2 text-left transition-colors ${
                      selected
                        ? "bg-blue-500/15 ring-1 ring-blue-500/40"
                        : "hover:bg-zinc-800/60"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDot(run.status)} ${
                          run.status === "running" ? "animate-pulse" : ""
                        }`}
                      />
                      <span className="truncate text-xs font-medium text-zinc-200">
                        {run.run_type}
                      </span>
                      <span className="ml-auto text-[10px] capitalize text-zinc-500">
                        {run.status}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center justify-between pl-3.5 font-mono text-[10px] text-zinc-600">
                      <span>{run.id.slice(0, 8)}</span>
                      <span>{dur != null ? formatDuration(dur) : formatTime(run.started_at)}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
