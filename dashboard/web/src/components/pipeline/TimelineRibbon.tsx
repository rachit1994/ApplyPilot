import { useMemo, type CSSProperties } from "react";
import type { RunEvent } from "../../api";

/** Pipeline phases shown on the timeline ribbon (req #3 / variant A). */
export type TimelinePhase =
  | "discover"
  | "enrich"
  | "score"
  | "tailor"
  | "cover"
  | "pdf"
  | "apply"
  | "refer";

export const TIMELINE_PHASES: TimelinePhase[] = [
  "discover",
  "enrich",
  "score",
  "tailor",
  "cover",
  "pdf",
  "apply",
  "refer",
];

/** Phase colors from docs/dashboard-mockups/variant-A-mission-control.html */
export const PHASE_COLORS: Record<TimelinePhase, string> = {
  discover: "#7dd3fc",
  enrich: "#c4b5fd",
  score: "#a78bfa",
  tailor: "#f0abfc",
  cover: "#fb7185",
  pdf: "#fbbf24",
  apply: "#4ade80",
  refer: "#2dd4bf",
};

export const TIMELINE_WARN_COLOR = "#f5b042";
export const TIMELINE_BAD_COLOR = "#f76b6b";

const WINDOW_MS = 30 * 60 * 1000;
const MIN_SEGMENT_PCT = 0.35;
const GAP_MIN_PCT = 0.15;

type SegmentTone = "normal" | "warn" | "bad";

type RibbonSegment = {
  id: string;
  kind: "phase" | "gap";
  phase?: TimelinePhase;
  widthPct: number;
  tone: SegmentTone;
  tooltip: string;
};

export type TimelineRibbonProps = {
  events: RunEvent[];
  className?: string;
};

function mergeClass(...parts: Array<string | false | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

function parseEventMs(iso: string | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function isTimelinePhase(value: string): value is TimelinePhase {
  return (TIMELINE_PHASES as readonly string[]).includes(value);
}

function resolveEventPhase(event: RunEvent): TimelinePhase | null {
  if (event.stage && isTimelinePhase(event.stage)) {
    return event.stage;
  }

  const message = (event.message ?? "").toLowerCase();
  const eventType = event.event_type ?? "";

  if (eventType.startsWith("stage_") && event.stage && isTimelinePhase(event.stage)) {
    return event.stage;
  }

  if (
    message.includes("apply") ||
    message.includes("greenhouse") ||
    message.includes("workday") ||
    message.includes("lever ") ||
    message.includes("application")
  ) {
    return "apply";
  }

  if (message.includes("outreach") || message.includes("openoutreach")) {
    return "refer";
  }

  if (eventType === "log") {
    for (const phase of TIMELINE_PHASES) {
      if (message.includes(phase)) return phase;
    }
  }

  return null;
}

function segmentTone(event: RunEvent, phase: TimelinePhase): SegmentTone {
  if (event.event_type === "stage_error" || event.level === "error") return "bad";
  if (event.level === "warning") return "warn";

  const message = (event.message ?? "").toLowerCase();
  if (
    message.includes("submitted_unverified") ||
    message.includes("needs check") ||
    message.includes("paused") ||
    message.includes("mfa")
  ) {
    return "warn";
  }
  if (message.includes("failed") || message.includes("form_changed") || message.includes("error")) {
    return phase === "apply" ? "bad" : "warn";
  }
  return "normal";
}

function segmentColor(phase: TimelinePhase, tone: SegmentTone): string {
  if (tone === "bad") return TIMELINE_BAD_COLOR;
  if (tone === "warn") return TIMELINE_WARN_COLOR;
  return PHASE_COLORS[phase];
}

function formatAxisTime(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatTooltipTime(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function eventLabel(event: RunEvent, phase: TimelinePhase): string {
  const parts: string[] = [phase];
  if (event.event_type && event.event_type !== "log") {
    parts.push(event.event_type.replace(/_/g, " "));
  }
  const msg = event.message?.trim();
  if (msg) parts.push(msg.length > 72 ? `${msg.slice(0, 69)}…` : msg);
  return parts.join(" · ");
}

function shouldSkipEvent(event: RunEvent): boolean {
  const t = event.event_type ?? "";
  return t === "stats_tick" || t === "run_started" || t === "run_finished";
}

type TimedRibbonEvent = {
  event: RunEvent;
  ms: number;
  phase: TimelinePhase;
  tone: SegmentTone;
};

function collectWindowEvents(events: RunEvent[], windowEnd: number): TimedRibbonEvent[] {
  const windowStart = windowEnd - WINDOW_MS;
  const rows: TimedRibbonEvent[] = [];

  for (const event of events) {
    if (shouldSkipEvent(event)) continue;
    const ms = parseEventMs(event.created_at);
    if (ms == null || ms < windowStart || ms > windowEnd) continue;

    const phase = resolveEventPhase(event);
    if (!phase) continue;

    rows.push({
      event,
      ms,
      phase,
      tone: segmentTone(event, phase),
    });
  }

  rows.sort((a, b) => a.ms - b.ms);
  return rows;
}

function buildSegments(
  timed: TimedRibbonEvent[],
  windowStart: number,
  windowEnd: number,
): RibbonSegment[] {
  if (timed.length === 0) return [];

  const segments: RibbonSegment[] = [];
  let cursor = windowStart;

  timed.forEach((row, index) => {
    const gapPct = ((row.ms - cursor) / WINDOW_MS) * 100;
    if (gapPct >= GAP_MIN_PCT) {
      segments.push({
        id: `gap-${index}-${cursor}`,
        kind: "gap",
        widthPct: gapPct,
        tone: "normal",
        tooltip: "",
      });
    }

    const nextMs = timed[index + 1]?.ms ?? windowEnd;
    const spanMs = Math.max(nextMs - row.ms, WINDOW_MS * (MIN_SEGMENT_PCT / 100));
    const widthPct = Math.max(MIN_SEGMENT_PCT, (spanMs / WINDOW_MS) * 100);

    segments.push({
      id: `seg-${row.event.id ?? index}-${row.ms}`,
      kind: "phase",
      phase: row.phase,
      widthPct,
      tone: row.tone,
      tooltip: `${eventLabel(row.event, row.phase)}\n${formatTooltipTime(row.ms)}`,
    });

    cursor = row.ms + spanMs;
  });

  const tailPct = ((windowEnd - cursor) / WINDOW_MS) * 100;
  if (tailPct >= GAP_MIN_PCT) {
    segments.push({
      id: "gap-tail",
      kind: "gap",
      widthPct: tailPct,
      tone: "normal",
      tooltip: "",
    });
  }

  const total = segments.reduce((sum, s) => sum + s.widthPct, 0);
  if (total > 0 && Math.abs(total - 100) > 0.01) {
    const scale = 100 / total;
    for (const seg of segments) {
      seg.widthPct *= scale;
    }
  }

  return segments;
}

const PLACEHOLDER_SEGMENTS: RibbonSegment[] = [
  {
    id: "ph-1",
    kind: "phase",
    phase: "discover",
    widthPct: 4,
    tone: "normal",
    tooltip: "discover · jobspy · 142 jobs\n15:12:04",
  },
  {
    id: "ph-2",
    kind: "phase",
    phase: "discover",
    widthPct: 2,
    tone: "normal",
    tooltip: "discover · workday · 22 jobs\n15:13:10",
  },
  { id: "ph-gap-1", kind: "gap", widthPct: 1, tone: "normal", tooltip: "" },
  {
    id: "ph-3",
    kind: "phase",
    phase: "enrich",
    widthPct: 7,
    tone: "normal",
    tooltip: "enrich · 180 jobs fetched\n15:14:22",
  },
  {
    id: "ph-4",
    kind: "phase",
    phase: "score",
    widthPct: 5,
    tone: "normal",
    tooltip: "score · 180 scored, 47 ≥ 7.0\n15:16:01",
  },
  {
    id: "ph-5",
    kind: "phase",
    phase: "tailor",
    widthPct: 6,
    tone: "normal",
    tooltip: "tailor · 18 resumes\n15:18:40",
  },
  {
    id: "ph-6",
    kind: "phase",
    phase: "cover",
    widthPct: 3,
    tone: "normal",
    tooltip: "cover · 18 letters\n15:20:05",
  },
  {
    id: "ph-7",
    kind: "phase",
    phase: "pdf",
    widthPct: 1,
    tone: "normal",
    tooltip: "pdf · 18 rendered\n15:20:48",
  },
  { id: "ph-gap-2", kind: "gap", widthPct: 0.5, tone: "normal", tooltip: "" },
  {
    id: "ph-8",
    kind: "phase",
    phase: "apply",
    widthPct: 8,
    tone: "normal",
    tooltip: "apply · Camber, Anthropic (verified)\n15:22:11",
  },
  {
    id: "ph-9",
    kind: "phase",
    phase: "apply",
    widthPct: 1,
    tone: "warn",
    tooltip: "apply · Acme · paused for MFA\n15:23:02",
  },
  {
    id: "ph-10",
    kind: "phase",
    phase: "apply",
    widthPct: 6,
    tone: "normal",
    tooltip: "apply · 4 jobs · 3 verified\n15:24:18",
  },
  {
    id: "ph-11",
    kind: "phase",
    phase: "apply",
    widthPct: 1.5,
    tone: "bad",
    tooltip: "apply · Stripe · failed: form_changed\n15:26:44",
  },
  {
    id: "ph-12",
    kind: "phase",
    phase: "apply",
    widthPct: 2,
    tone: "warn",
    tooltip: "3 submitted_unverified flagged\n15:28:09",
  },
  {
    id: "ph-13",
    kind: "phase",
    phase: "refer",
    widthPct: 5,
    tone: "normal",
    tooltip: "refer · 11 outreach drafts\n15:30:55",
  },
  {
    id: "ph-14",
    kind: "phase",
    phase: "apply",
    widthPct: 7,
    tone: "normal",
    tooltip: "apply · in progress\n15:38:12",
  },
  { id: "ph-gap-3", kind: "gap", widthPct: 34, tone: "normal", tooltip: "" },
];

function segmentStyle(seg: RibbonSegment): CSSProperties {
  if (seg.kind === "gap") {
    return { width: `${seg.widthPct}%`, flexShrink: 0 };
  }
  const phase = seg.phase ?? "discover";
  const color = segmentColor(phase, seg.tone);
  return {
    width: `${seg.widthPct}%`,
    flexShrink: 0,
    background: color,
    opacity: seg.tone === "normal" ? 0.88 : seg.tone === "warn" ? 0.72 : 0.62,
  };
}

export function TimelineRibbon({ events, className }: TimelineRibbonProps) {
  const windowEnd = Date.now();

  const { segments, windowStart, eventCount, isPlaceholder, isEmptyWindow } = useMemo(() => {
    if (events.length === 0) {
      const end = windowEnd;
      return {
        segments: PLACEHOLDER_SEGMENTS,
        windowStart: end - WINDOW_MS,
        eventCount: 247,
        isPlaceholder: true,
        isEmptyWindow: false,
      };
    }

    const timed = collectWindowEvents(events, windowEnd);
    const start = windowEnd - WINDOW_MS;
    if (timed.length === 0) {
      return {
        segments: [] as RibbonSegment[],
        windowStart: start,
        eventCount: 0,
        isPlaceholder: false,
        isEmptyWindow: true,
      };
    }

    return {
      segments: buildSegments(timed, start, windowEnd),
      windowStart: start,
      eventCount: timed.length,
      isPlaceholder: false,
      isEmptyWindow: false,
    };
  }, [events, windowEnd]);

  const axisMarks = useMemo(() => {
    const marks: number[] = [];
    for (let i = 0; i < 6; i += 1) {
      marks.push(windowStart + (WINDOW_MS / 5) * i);
    }
    return marks;
  }, [windowStart]);

  const subline = isPlaceholder
    ? `${formatAxisTime(windowStart)} → ${formatAxisTime(windowEnd)} · ${eventCount} events · hover for detail`
    : isEmptyWindow
      ? `${formatAxisTime(windowStart)} → ${formatAxisTime(windowEnd)} · no phase events in window`
      : `${formatAxisTime(windowStart)} → ${formatAxisTime(windowEnd)} · ${eventCount} events · hover for detail`;

  return (
    <section
      className={mergeClass(
        "border-b border-[var(--color-panel-border)] bg-[var(--color-panel)] px-5 py-3",
        className,
      )}
      aria-label="Pipeline activity timeline"
    >
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
          Last 30 minutes
        </h3>
        <p className="font-mono text-[11px] tabular-nums text-ink-4">{subline}</p>
      </div>

      <div className="scroll-thin overflow-x-auto pb-1">
        <div
          className="flex h-8 min-w-[720px] overflow-hidden rounded border border-[var(--color-panel-border)] bg-panel-elevated/60"
          role="img"
          aria-label={
            isPlaceholder
              ? "Sample timeline placeholder"
              : isEmptyWindow
                ? "No events in the last thirty minutes"
                : `Timeline with ${eventCount} events`
          }
        >
          {isEmptyWindow ? (
            <div className="flex h-full w-full items-center justify-center px-3 text-[11px] text-ink-4">
              No phase events in the last 30 minutes — start a run or wait for activity.
            </div>
          ) : (
            segments.map((seg) => (
              <div
                key={seg.id}
                className={mergeClass(
                  "h-full transition-opacity hover:opacity-100",
                  seg.kind === "gap" && "bg-panel-elevated/80",
                )}
                style={segmentStyle(seg)}
                title={seg.tooltip || undefined}
              />
            ))
          )}
        </div>

        <div className="mt-1.5 grid min-w-[720px] grid-cols-6 font-mono text-[10px] tabular-nums text-ink-4">
          {axisMarks.map((ms) => (
            <span
              key={ms}
              className="border-l border-[var(--color-panel-border)] pl-1.5 first:border-l-0 first:pl-0"
            >
              {formatAxisTime(ms)}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap gap-x-3.5 gap-y-1 font-mono text-[10px] text-ink-4">
        {TIMELINE_PHASES.map((phase) => (
          <span key={phase} className="inline-flex items-center gap-1.5">
            <i
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: PHASE_COLORS[phase] }}
              aria-hidden
            />
            {phase}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <i
            className="inline-block h-2 w-2 rounded-sm"
            style={{ background: TIMELINE_WARN_COLOR }}
            aria-hidden
          />
          needs check
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i
            className="inline-block h-2 w-2 rounded-sm"
            style={{ background: TIMELINE_BAD_COLOR }}
            aria-hidden
          />
          failed
        </span>
      </div>
    </section>
  );
}
