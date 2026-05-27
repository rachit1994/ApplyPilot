import type { Application } from "../api";

export type ApplyStatusFilter =
  | "all"
  | "needs_action"
  | "applied"
  | "submitted_unverified"
  | "failed"
  | "manual";

export function applyStatusFilterFromUrl(filter: string | null): ApplyStatusFilter {
  if (filter === "needs") return "needs_action";
  if (filter === "unverified") return "submitted_unverified";
  if (filter === "applied") return "applied";
  if (filter === "failed") return "failed";
  if (filter === "manual") return "manual";
  return "all";
}

export function apiStatusForFilter(filter: ApplyStatusFilter): string | undefined {
  if (filter === "all") return undefined;
  if (filter === "needs_action") return undefined;
  return filter;
}

export function needsHumanIntervention(app: Application): boolean {
  const status = app.apply_status ?? "unknown";
  if (status === "submitted_unverified" || status === "manual") return true;
  if (status !== "failed") return false;
  const raw = (app.apply_error ?? "").toLowerCase();
  return (
    raw.includes("sso_login_needed") ||
    raw.includes("pause_for_human") ||
    raw.includes("email verification") ||
    raw.includes("verify your email") ||
    raw.includes("verification needed")
  );
}

export function parseApplyErrorReasons(
  applyError: string | null | undefined,
): string[] {
  if (!applyError?.trim()) return [];
  const raw = applyError.trim();
  const prefix = "submitted_unverified:";
  if (raw.startsWith(prefix)) {
    const body = raw.slice(prefix.length).trim();
    if (!body) return [];
    return body.split(";").map((s) => s.trim()).filter(Boolean);
  }
  return [raw];
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function statusChipClass(status: string): string {
  if (status === "applied") return "bg-good/15 text-good";
  if (status === "submitted_unverified") return "bg-warn/15 text-warn";
  if (status === "failed") return "bg-bad/15 text-bad";
  if (status === "manual") return "bg-panel-elevated text-ink-3";
  return "bg-panel-elevated text-ink-3";
}

export function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

export function applicationSummaryLine(app: Application): string | null {
  if (app.apply_error) {
    const reasons = parseApplyErrorReasons(app.apply_error);
    return reasons[0] ?? app.apply_error;
  }
  const n = app.form_filled?.field_count ?? app.form_filled?.fields?.length ?? 0;
  if (n > 0) {
    return `${n} field${n === 1 ? "" : "s"} captured`;
  }
  return null;
}
