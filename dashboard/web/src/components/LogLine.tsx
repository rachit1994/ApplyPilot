import { useState } from "react";
import type { RunEvent } from "../api";
import { effectiveLogLevel } from "../utils/logLevel";

const WORKER_RE = /\[W(\d+)\]/;
const LEVEL_PREFIX_RE =
  /^(?:\d{2}:\d{2}:\d{2}\s+-\s+)?(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+-\s+/i;

export function extractWorkerId(message: string | undefined): string | null {
  if (!message) return null;
  const match = message.match(WORKER_RE);
  return match ? `W${match[1]}` : null;
}

export function formatLogTimestamp(createdAt: string | undefined): string {
  if (!createdAt) return "—";
  const tIdx = createdAt.indexOf("T");
  if (tIdx === -1) return createdAt.slice(11, 19);
  const timePart = createdAt.slice(tIdx + 1);
  const dot = timePart.indexOf(".");
  if (dot !== -1) return timePart.slice(0, dot + 4);
  return timePart.slice(0, 8);
}

export function formatLineForCopy(event: RunEvent): string {
  const parts: string[] = [];
  if (event.created_at) parts.push(formatLogTimestamp(event.created_at));
  parts.push(levelMeta(event).label);
  const worker = extractWorkerId(event.message);
  if (worker) parts.push(worker);
  if (event.stage) parts.push(`[${event.stage}]`);
  const msg = displayMessage(event.message);
  if (msg) parts.push(msg);
  return parts.join(" ");
}

function displayMessage(message: string | undefined): string {
  if (!message) return "";
  return message.replace(WORKER_RE, "").replace(LEVEL_PREFIX_RE, "").trim();
}

function levelMeta(event: RunEvent): {
  label: string;
  badgeClass: string;
  messageClass: string;
} {
  const level = effectiveLogLevel(event);
  if (level === "error") {
    return {
      label: "ERR",
      badgeClass: "text-red-400",
      messageClass: "text-red-200",
    };
  }
  if (level === "warning") {
    return {
      label: "WRN",
      badgeClass: "text-warning",
      messageClass: "text-warning",
    };
  }
  return {
    label: "INF",
    badgeClass: "text-ink-4",
    messageClass: "text-warning/90",
  };
}

function workerClass(worker: string): string {
  const n = Number.parseInt(worker.slice(1), 10);
  if (n === 0) return "text-sky-300";
  if (n === 1) return "text-accent";
  if (n === 2) return "text-fuchsia-300";
  return "text-ink-3";
}

type Props = {
  event: RunEvent;
  even?: boolean;
};

export function LogLine({ event, even }: Props) {
  const [copied, setCopied] = useState(false);
  const { label, badgeClass, messageClass } = levelMeta(event);
  const worker = extractWorkerId(event.message);
  const phase = event.stage ?? (event.event_type !== "log" ? event.event_type : "");
  const message = displayMessage(event.message);

  const copyLine = async () => {
    try {
      await navigator.clipboard.writeText(formatLineForCopy(event));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div
      className={`group grid grid-cols-[72px_32px_40px_56px_minmax(0,1fr)_28px] items-baseline gap-x-2.5 px-3.5 py-0.5 font-mono text-[14px] leading-[1.6] ${
        even ? "bg-white/[0.012]" : ""
      } hover:bg-panel-elevated/70`}
    >
      <span className="tabular-nums text-ink-4">{formatLogTimestamp(event.created_at)}</span>
      <span className={`text-[10px] font-semibold uppercase tracking-wider ${badgeClass}`}>
        {label}
      </span>
      <span className={`text-[10.5px] ${worker ? workerClass(worker) : "text-ink-5"}`}>
        {worker ?? "—"}
      </span>
      <span className="truncate text-[10.5px] text-ink-4">{phase || "—"}</span>
      <span className={`min-w-0 break-words ${messageClass}`}>{message || "—"}</span>
      <button
        type="button"
        onClick={copyLine}
        title="Copy line"
        className="justify-self-end rounded border border-transparent px-1 py-0.5 text-[10px] text-ink-5 opacity-0 transition hover:border-panel-border-strong hover:bg-panel-muted hover:text-ink-2 group-hover:opacity-100"
        aria-label="Copy log line"
      >
        {copied ? "✓" : "⎘"}
      </button>
    </div>
  );
}
