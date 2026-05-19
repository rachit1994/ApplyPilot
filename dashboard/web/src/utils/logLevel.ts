import type { RunEvent } from "../api";

const LOG_LEVEL_PREFIX =
  /^(?:\d{2}:\d{2}:\d{2}\s+-\s+)?(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+-\s+/i;

/** Prefer Python logging prefix in message over stored level (fixes legacy stderr tagging). */
export function effectiveLogLevel(event: RunEvent): "info" | "warning" | "error" {
  if (event.event_type === "stage_error") return "error";

  const message = event.message ?? "";
  const match = message.match(LOG_LEVEL_PREFIX);
  if (match) {
    const token = match[1].toUpperCase();
    if (token === "ERROR" || token === "CRITICAL") return "error";
    if (token === "WARNING" || token === "WARN") return "warning";
    return "info";
  }

  const level = (event.level ?? "info").toLowerCase();
  if (level === "error") return "error";
  if (level === "warning") return "warning";
  return "info";
}

export function isLogError(event: RunEvent): boolean {
  return effectiveLogLevel(event) === "error";
}
