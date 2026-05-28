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
    <section className="panel" style={{ minHeight: "min(72vh, 640px)", display: "flex", flexDirection: "column" }}>
      <div className="panel__head panel__head--inset">
        <div>
          <div className="panel__title">Live logs</div>
          <div className="panel__sub">{eventCountLabel}</div>
        </div>
      </div>

      {combinedErrors.length > 0 ? (
        <div style={{ borderTop: "1px solid var(--hair)" }}>
          <button
            type="button"
            onClick={() => setErrorsOpen((open) => !open)}
            className="btn btn--ghost"
            style={{
              width: "100%",
              justifyContent: "space-between",
              borderRadius: 0,
              color: "#ff8a8a",
              fontSize: 11.5,
            }}
          >
            <span>
              {combinedErrors.length} error
              {combinedErrors.length === 1 ? "" : "s"}
            </span>
            <span>{errorsOpen ? "▼" : "▶"}</span>
          </button>
          {errorsOpen ? (
            <div style={{ maxHeight: 112, overflow: "hidden" }}>
            <VirtualScroll
              items={combinedErrors}
              getItemKey={(e, i) => e.id ?? `err-${i}`}
              estimateSize={LOG_LINE_ESTIMATE_PX}
              className="devlog__list"
            >
              {(e, i) => <LogLine event={e} even={i % 2 === 1} />}
            </VirtualScroll>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="devlog__bar" role="toolbar" aria-label="Log filters">
        {FILTER_CHIPS.map((chip) => (
          <button
            key={chip.id}
            type="button"
            onClick={() => setCategoryFilter(chip.id)}
            className={categoryFilter === chip.id ? "chip chip--on" : "chip"}
          >
            {chip.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <VirtualScroll
          scrollRef={logsScrollRef}
          items={filtered}
          getItemKey={(e, i) => e.id ?? i}
          estimateSize={LOG_LINE_ESTIMATE_PX}
          className="devlog__list"
          onScroll={syncStickToBottom}
          stickToBottom={stickToBottom}
          empty={
            <p className="panel__sub" style={{ padding: "24px 18px" }}>
              {logEvents.length === 0
                ? "Start a run to stream logs here."
                : "No log lines match this filter."}
            </p>
          }
        >
          {(e, i) => <LogLine event={e} even={i % 2 === 1} />}
        </VirtualScroll>
      </div>
    </section>
  );
}
