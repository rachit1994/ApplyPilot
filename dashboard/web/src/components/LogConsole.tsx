import { useMemo, useState } from "react";
import type { RunEvent } from "../api";

type Props = {
  events: RunEvent[];
  errors: RunEvent[];
};

type LevelFilter = "all" | "info" | "warning" | "error";

function levelClass(level?: string, eventType?: string): string {
  if (eventType === "stage_error" || level === "error") return "text-red-300";
  if (level === "warning" || level === "info") return "text-amber-300";
  if (eventType?.startsWith("stage_")) return "text-sky-300";
  return "text-zinc-300";
}

function matchesFilter(e: RunEvent, filter: LevelFilter): boolean {
  if (filter === "all") return true;
  if (filter === "error") {
    return e.level === "error" || e.event_type === "stage_error";
  }
  if (filter === "warning") return e.level === "warning";
  return e.level !== "error" && e.level !== "warning" && e.event_type !== "stage_error";
}

function formatLine(e: RunEvent): string {
  const parts: string[] = [];
  if (e.created_at) parts.push(e.created_at.slice(11, 19));
  if (e.stage) parts.push(`[${e.stage}]`);
  if (e.event_type !== "log") parts.push(`${e.event_type}:`);
  if (e.message) parts.push(e.message);
  return parts.join(" ");
}

export function LogConsole({ events, errors }: Props) {
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("all");
  const [errorsOpen, setErrorsOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  const logEvents = useMemo(
    () => events.filter((e) => e.event_type === "log" || e.message),
    [events],
  );

  const filtered = useMemo(
    () => logEvents.filter((e) => matchesFilter(e, levelFilter)),
    [logEvents, levelFilter],
  );

  const copyLogs = async () => {
    const text = filtered.map(formatLine).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  const filters: { id: LevelFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "info", label: "Info" },
    { id: "warning", label: "Warn" },
    { id: "error", label: "Error" },
  ];

  return (
    <section className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <header className="panel-header shrink-0">
        <h2 className="panel-title">Live logs</h2>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zinc-600">{filtered.length} lines</span>
          <button
            type="button"
            onClick={copyLogs}
            disabled={filtered.length === 0}
            className="rounded-md border border-zinc-700 px-2 py-1 text-[10px] text-zinc-400 hover:bg-zinc-800 disabled:opacity-40"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </header>

      {errors.length > 0 && (
        <div className="shrink-0 border-b border-red-900/40">
          <button
            type="button"
            onClick={() => setErrorsOpen((o) => !o)}
            className="flex w-full items-center justify-between px-4 py-2 text-left text-xs font-medium text-red-300 hover:bg-red-950/20"
          >
            <span>
              {errors.length} error{errors.length === 1 ? "" : "s"}
            </span>
            <span className="text-red-500/80">{errorsOpen ? "▼" : "▶"}</span>
          </button>
          {errorsOpen && (
            <div className="scroll-thin max-h-32 overflow-y-auto border-t border-red-900/30 bg-red-950/20 px-4 py-2 font-mono text-[11px] leading-relaxed text-red-200">
              {errors.map((e, i) => (
                <div key={e.id ?? `err-${i}`} className="mb-1">
                  {formatLine(e)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex shrink-0 gap-1 border-b border-zinc-800/80 px-3 py-2">
        {filters.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setLevelFilter(f.id)}
            className={`rounded-md px-2 py-0.5 text-[10px] font-medium ${
              levelFilter === f.id
                ? "bg-zinc-700 text-zinc-100"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed">
        {filtered.length === 0 ? (
          <p className="text-zinc-500">Start a run to stream logs here.</p>
        ) : (
          filtered.map((e, i) => (
            <div key={e.id ?? i} className={levelClass(e.level, e.event_type)}>
              {e.created_at && (
                <span className="text-zinc-600">{e.created_at.slice(11, 19)} </span>
              )}
              {e.stage && <span className="text-zinc-500">[{e.stage}] </span>}
              {e.event_type !== "log" && (
                <span className="text-zinc-500">{e.event_type}: </span>
              )}
              {e.message}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
