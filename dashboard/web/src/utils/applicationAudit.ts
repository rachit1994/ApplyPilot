import type { Application } from "../api";

export type ApplyStatusFilter =
  | "all"
  | "needs_action"
  | "claude_escalated"
  | "applied"
  | "submitted_unverified"
  | "failed"
  | "manual";

export function applyStatusFilterFromUrl(filter: string | null): ApplyStatusFilter {
  if (filter === "needs" || filter === "needs_action") return "needs_action";
  if (filter === "unverified") return "submitted_unverified";
  if (filter === "applied") return "applied";
  if (filter === "failed") return "failed";
  if (filter === "manual") return "manual";
  if (filter === "claude" || filter === "claude_escalated") return "claude_escalated";
  return "all";
}

export function apiStatusForFilter(filter: ApplyStatusFilter): string | undefined {
  if (filter === "all") return undefined;
  if (filter === "needs_action") return undefined;
  if (filter === "claude_escalated") return undefined;
  return filter;
}

export function apiNeedsAttentionForFilter(filter: ApplyStatusFilter): boolean {
  return filter === "needs_action";
}

export function applicationsIncludeFailedForFilter(filter: ApplyStatusFilter): boolean {
  if (filter === "applied" || filter === "submitted_unverified") return false;
  return true;
}

export function isClaudeEscalated(app: Application): boolean {
  const err = (app.apply_error ?? "").toLowerCase();
  if (err.startsWith("pending_claude_rescue")) return true;
  return false;
}

/** Clear apply state so the next `applypilot apply` run can pick this job again. */
export function canRequeueApply(app: Application): boolean {
  const status = app.apply_status ?? "";
  return status === "failed" || status === "manual" || status === "submitted_unverified";
}

/** Reset ghost/unverified submission and allow another apply attempt. */
export function canRetryUnverifiedApply(app: Application): boolean {
  return (app.apply_status ?? "") === "submitted_unverified";
}

export function needsHumanIntervention(app: Application): boolean {
  const status = app.apply_status ?? "unknown";
  if (status === "submitted_unverified" || status === "manual") return true;
  if (status !== "failed") return false;
  const raw = (app.apply_error ?? "").toLowerCase();
  return (
    raw.includes("sso_login_needed") ||
    raw.includes("awaiting_login") ||
    raw.includes("login_required_no_google") ||
    raw.includes("pause_for_human") ||
    raw.includes("email verification") ||
    raw.includes("verify your email") ||
    raw.includes("verification needed")
  );
}

const APPLY_ERROR_PREFIXES = [
  "submitted_unverified:",
  "failed:",
  "manual:",
  "applied:",
] as const;

const HUMAN_APPLY_REASONS: Record<string, string> = {
  claude_quota_exhausted: "Claude quota exhausted",
  worker_interrupted: "Worker stopped",
  sso_login_needed: "SSO login needed",
  login_required: "Login required",
  login_required_no_google: "Login required, no Google sign-in",
  pause_for_human: "Paused for you",
  pending_claude_rescue: "Waiting for Claude retry",
  no_confirmation: "No submit confirmation",
  captcha: "CAPTCHA blocked",
  timeout: "Timed out",
};

export function parseApplyErrorReasons(
  applyError: string | null | undefined,
): string[] {
  if (!applyError?.trim()) return [];
  const parts = splitApplyErrorBody(applyError.trim());
  return parts.length > 0 ? parts : [applyError.trim()];
}

function splitApplyErrorBody(raw: string): string[] {
  let body = raw;
  const lower = body.toLowerCase();
  for (const prefix of APPLY_ERROR_PREFIXES) {
    if (lower.startsWith(prefix)) {
      body = body.slice(prefix.length).trim();
      break;
    }
  }
  if (!body) return [];
  if (body.includes(";")) {
    return body.split(";").map((s) => s.trim()).filter(Boolean);
  }
  return [body];
}

function humanizeApplyReasonToken(token: string): string {
  const key = token.trim().toLowerCase();
  if (HUMAN_APPLY_REASONS[key]) return HUMAN_APPLY_REASONS[key];
  if (key.startsWith("awaiting_login:")) {
    const domain = token.slice("awaiting_login:".length).trim();
    return domain ? `Awaiting login: ${domain}` : "Awaiting login";
  }
  if (key.includes("email verification") || key.includes("verify your email")) {
    return "Email verification needed";
  }
  return token.replace(/_/g, " ");
}

export function formatApplyErrorForDisplay(applyError: string): string {
  const parts = parseApplyErrorReasons(applyError);
  return parts.map(humanizeApplyReasonToken).join(" · ");
}

/** Best timestamp for list rows: applied time, else last attempt. */
export function applicationAttemptAt(app: Application): string | null {
  return app.applied_at ?? app.last_attempted_at ?? null;
}

export function applicationDateCaption(app: Application): string {
  if (app.applied_at) return "Applied";
  if (app.last_attempted_at) return "Attempted";
  return "Date";
}

/** Short reason for table rows on any status when we have error or outcome text. */
export function applicationReasonLine(app: Application): string | null {
  if (app.apply_error?.trim()) {
    return formatApplyErrorForDisplay(app.apply_error);
  }
  if ((app.apply_status ?? "") === "manual") {
    return "Needs review";
  }
  return applicationSummaryLine(app);
}

export function applicationReasonTone(
  status: string,
): "failed" | "warn" | "muted" | "neutral" {
  if (status === "failed") return "failed";
  if (status === "submitted_unverified" || status === "manual") return "warn";
  if (status === "applied") return "muted";
  return "neutral";
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || ms <= 0) return "—";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
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
