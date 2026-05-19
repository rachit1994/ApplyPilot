import { useEffect, useMemo, useRef, useState } from "react";
import type { RunEvent } from "../api";
import { effectiveLogLevel, isLogError } from "../utils/logLevel";
import { VirtualScroll } from "./VirtualScroll";

type Props = {
  events: RunEvent[];
  errors: RunEvent[];
};

type LevelFilter = "all" | "info" | "warning" | "error";

function levelClass(event: RunEvent): string {
  const level = effectiveLogLevel(event);
  if (level === "error") return "text-red-300";
  if (level === "warning" || level === "info") return "text-amber-300";
  if (event.event_type?.startsWith("stage_")) return "text-sky-300";
  return "text-zinc-300";
}

function matchesFilter(e: RunEvent, filter: LevelFilter): boolean {
  const level = effectiveLogLevel(e);
  if (filter === "all") return true;
  if (filter === "error") return level === "error";
  if (filter === "warning") return level === "warning";
  return level === "info";
}

function formatLine(e: RunEvent): string {
  const parts: string[] = [];
  if (e.created_at) parts.push(e.created_at.slice(11, 19));
  if (e.stage) parts.push(`[${e.stage}]`);
  if (e.event_type !== "log") parts.push(`${e.event_type}:`);
  if (e.message) parts.push(e.message);
  return parts.join(" ");
}

const LOG_SCROLL_TAIL_PX = 80;
const LOG_BODY_CLASS =
  "scroll-thin max-h-80 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed";
const LOG_LINE_ESTIMATE_PX = 20;

export function LogConsole({ events, errors: stageErrors }: Props) {
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("all");
  const [errorsOpen, setErrorsOpen] = useState(true);
  const [copied, setCopied] = useState(false);
  const [stickToBottom, setStickToBottom] = useState(true);
  const logsScrollRef = useRef<HTMLDivElement>(null);

  const logEvents = useMemo(
    () => events.filter((e) => e.event_type === "log"),
    [events],
  );

  const logErrors = useMemo(
    () => logEvents.filter((e) => isLogError(e)),
    [logEvents],
  );

  const filtered = useMemo(
    () => logEvents.filter((e) => matchesFilter(e, levelFilter)),
    [logEvents, levelFilter],
  );

  const combinedErrors = useMemo(
    () => [...stageErrors, ...logErrors],
    [stageErrors, logErrors],
  );

  useEffect(() => {
    if (logEvents.length === 0) {
      setStickToBottom(true);
    }
  }, [logEvents.length]);

  const syncStickToBottom = () => {
    const el = logsScrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setStickToBottom(distanceFromBottom <= LOG_SCROLL_TAIL_PX);
  };

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
    <section className="panel flex flex-col overflow-hidden">
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

      {combinedErrors.length > 0 && (
        <div className="shrink-0 border-b border-red-900/40">
          <button
            type="button"
            onClick={() => setErrorsOpen((o) => !o)}
            className="flex w-full items-center justify-between px-4 py-2 text-left text-xs font-medium text-red-300 hover:bg-red-950/20"
          >
            <span>
              {combinedErrors.length} error
              {combinedErrors.length === 1 ? "" : "s"}
            </span>
            <span className="text-red-500/80">{errorsOpen ? "▼" : "▶"}</span>
          </button>
          {errorsOpen && (
            <VirtualScroll
              items={combinedErrors}
              getItemKey={(e, i) => e.id ?? `err-${i}`}
              estimateSize={LOG_LINE_ESTIMATE_PX}
              className="scroll-thin max-h-32 overflow-y-auto border-t border-red-900/30 bg-red-950/20 px-4 py-2 font-mono text-[11px] leading-relaxed text-red-200"
            >
              {(e) => <div className="mb-1">{formatLine(e)}</div>}
            </VirtualScroll>
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

      <VirtualScroll
        scrollRef={logsScrollRef}
        items={filtered}
        getItemKey={(e, i) => e.id ?? i}
        estimateSize={LOG_LINE_ESTIMATE_PX}
        className={LOG_BODY_CLASS}
        onScroll={syncStickToBottom}
        stickToBottom={stickToBottom}
        empty={<p className="text-zinc-500">Start a run to stream logs here.</p>}
      >
        {(e) => (
          <div className={levelClass(e)}>
            {e.created_at && (
              <span className="text-zinc-600">{e.created_at.slice(11, 19)} </span>
            )}
            {e.stage && <span className="text-zinc-500">[{e.stage}] </span>}
            {e.event_type !== "log" && (
              <span className="text-zinc-500">{e.event_type}: </span>
            )}
            {e.message}
          </div>
        )}
      </VirtualScroll>
    </section>
  );
}
