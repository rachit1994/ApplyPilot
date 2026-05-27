import { useEffect, useMemo, useRef, useState } from "react";
import type { RunEvent } from "../api";
import { effectiveLogLevel, isLogError } from "../utils/logLevel";
import { LogLine } from "./LogLine";
import { VirtualScroll } from "./VirtualScroll";

type Props = {
  events: RunEvent[];
  errors: RunEvent[];
};

type CategoryFilter = "all" | "errors" | "apply" | "discover";

function matchesCategory(event: RunEvent, filter: CategoryFilter): boolean {
  if (filter === "all") return true;
  if (filter === "errors") return effectiveLogLevel(event) === "error";
  const stage = (event.stage ?? "").toLowerCase();
  const message = (event.message ?? "").toLowerCase();
  if (filter === "apply") {
    return (
      stage === "apply" ||
      stage === "verify" ||
      stage === "refer" ||
      message.includes("apply") ||
      message.includes("greenhouse") ||
      message.includes("lever") ||
      message.includes("workday")
    );
  }
  if (filter === "discover") {
    return (
      stage === "discover" ||
      message.includes("discover") ||
      message.includes("jobspy") ||
      message.includes("workatastartup") ||
      message.includes("smart extract")
    );
  }
  return true;
}

const LOG_SCROLL_TAIL_PX = 80;
const LOG_BODY_CLASS =
  "scroll-thin min-h-0 flex-1 overflow-y-auto py-1 font-mono text-[14px] leading-[1.6]";
const LOG_LINE_ESTIMATE_PX = 26;

const FILTER_CHIPS: { id: CategoryFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "errors", label: "Errors" },
  { id: "apply", label: "Apply" },
  { id: "discover", label: "Discover" },
];

export function LogConsole({ events, errors: stageErrors }: Props) {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [errorsOpen, setErrorsOpen] = useState(true);
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
    () => logEvents.filter((e) => matchesCategory(e, categoryFilter)),
    [logEvents, categoryFilter],
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

  const eventCountLabel =
    filtered.length === logEvents.length
      ? `${logEvents.length} events`
      : `${filtered.length} of ${logEvents.length} events`;

  return (
    <section className="panel flex h-[72vh] min-h-[72vh] flex-col overflow-hidden">
      <div className="sticky top-0 z-10 shrink-0 border-b border-[var(--hairline)] bg-[var(--panel)]">
        <header className="panel-header border-b-0 py-2.5">
          <h2 className="panel-title">Live logs</h2>
          <span className="font-mono text-[11px] tabular-nums text-ink-4">
            {eventCountLabel}
          </span>
        </header>

        {combinedErrors.length > 0 && (
          <div className="border-t border-red-900/30">
            <button
              type="button"
              onClick={() => setErrorsOpen((open) => !open)}
              className="flex w-full items-center justify-between px-3.5 py-1.5 text-left text-[11px] font-medium text-red-300 hover:bg-red-950/20"
            >
              <span>
                {combinedErrors.length} error
                {combinedErrors.length === 1 ? "" : "s"}
              </span>
              <span className="text-red-500/70">{errorsOpen ? "▼" : "▶"}</span>
            </button>
            {errorsOpen && (
              <VirtualScroll
                items={combinedErrors}
                getItemKey={(e, i) => e.id ?? `err-${i}`}
                estimateSize={LOG_LINE_ESTIMATE_PX}
                className="scroll-thin max-h-28 overflow-y-auto border-t border-red-900/25 bg-red-950/15 py-1"
              >
                {(e, i) => <LogLine event={e} even={i % 2 === 1} />}
              </VirtualScroll>
            )}
          </div>
        )}

        <div
          className="flex flex-wrap gap-1 border-t border-[var(--hairline)] px-3 py-2"
          role="toolbar"
          aria-label="Log filters"
        >
          {FILTER_CHIPS.map((chip) => (
            <button
              key={chip.id}
              type="button"
              onClick={() => setCategoryFilter(chip.id)}
              className={`rounded-[var(--rad-chip)] border px-2.5 py-0.5 text-[11px] font-medium transition ${
                categoryFilter === chip.id
                  ? "border-panel-border-strong bg-panel-muted text-ink"
                  : "border-transparent text-ink-4 hover:border-panel-border hover:text-ink-2"
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      <VirtualScroll
        scrollRef={logsScrollRef}
        items={filtered}
        getItemKey={(e, i) => e.id ?? i}
        estimateSize={LOG_LINE_ESTIMATE_PX}
        className={LOG_BODY_CLASS}
        onScroll={syncStickToBottom}
        stickToBottom={stickToBottom}
        empty={
          <p className="px-3.5 py-6 text-[14px] leading-[1.6] text-ink-4">
            {logEvents.length === 0
              ? "Start a run to stream logs here."
              : "No log lines match this filter."}
          </p>
        }
      >
        {(e, i) => <LogLine event={e} even={i % 2 === 1} />}
      </VirtualScroll>
    </section>
  );
}
