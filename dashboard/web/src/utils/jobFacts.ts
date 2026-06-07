import type { Job } from "../api";

/** Treat null, undefined, and whitespace-only strings as empty for detail UI. */
export function displayJobField(value: string | number | null | undefined): string {
  if (value == null) return "—";
  if (typeof value === "number") return String(value);
  const trimmed = value.trim();
  return trimmed || "—";
}

/** Prefer the employer segment from board labels like "Greenhouse:Affirm". */
export function companyLabelFromSite(site: string | null | undefined): string {
  if (!site?.trim()) return "—";
  const parts = site.split(":");
  const label = (parts.length > 1 ? parts[parts.length - 1] : site).trim();
  return label || site.trim();
}

export function formatSiteFilterLabel(site: string): string {
  const trimmed = site.trim();
  if (!trimmed) return "—";
  const parts = trimmed.split(":");
  if (parts.length > 1) {
    const board = parts[0].trim();
    const company = parts[parts.length - 1].trim();
    return company ? `${company} · ${board}` : trimmed;
  }
  return trimmed;
}

export function formatPreFilterReason(reason: string | null | undefined): string {
  if (!reason) return "—";
  const labels: Record<string, string> = {
    "title:junior_or_intern": "Junior or intern title",
    "title:exec_non_eng": "Executive non-engineering role",
    "title:adjacent_role": "Adjacent non-core role",
    "title:not_in_allowlist": "Title outside target roles",
    "location:reject_pattern": "Location outside target regions",
    "salary:below_floor": "Salary below floor",
    "description:blocked_keyword": "Blocked JD keyword",
    "description:junior_signal": "Junior signal in JD",
    "profile:low_keyword_overlap": "Low profile/JD keyword overlap",
    "embedding_low": "Low resume/JD embedding match",
  };
  return labels[reason] ?? reason.replace(/_/g, " ");
}

export function companyInitials(label: string): string {
  const cleaned = label.replace(/[^a-zA-Z0-9\s]/g, " ").trim();
  if (!cleaned) return "?";
  const words = cleaned.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return cleaned.slice(0, 2).toUpperCase();
}

export function inferRemoteFromLocation(location: string | null | undefined): string | null {
  if (!location?.trim()) return null;
  const loc = location.toLowerCase();
  const hasRemote = loc.includes("remote");
  const hasHybrid = loc.includes("hybrid");
  const hasOnsite =
    loc.includes("onsite") ||
    loc.includes("on-site") ||
    loc.includes("on site") ||
    loc.includes("in-office") ||
    loc.includes("in office") ||
    loc.includes("office-based");
  if (hasRemote && hasHybrid) return "Hybrid";
  if (hasRemote && hasOnsite) return "Mixed";
  if (hasRemote) return "Remote";
  if (hasHybrid) return "Hybrid";
  if (hasOnsite) return "On-site";
  return "On-site";
}

export function formatFitScoreDetail(job: Job): { text: string; accent: boolean } {
  if (job.fit_score != null) {
    return { text: `${job.fit_score}/10`, accent: job.fit_score >= 8 };
  }
  if (job.pre_fit_score != null) {
    return { text: `Pre-score ${job.pre_fit_score}/10`, accent: false };
  }
  if (job.pre_filter_reason) {
    return { text: "Filtered out", accent: false };
  }
  if (job.scored_at) {
    return { text: "Scored (no score stored)", accent: false };
  }
  if (job.full_description) {
    return { text: "Not scored yet", accent: false };
  }
  return { text: "Needs enrich", accent: false };
}

export function formatApplyStatusDetail(job: Job): string {
  if (job.apply_status) return job.apply_status;
  if (job.apply_error) return `Failed: ${job.apply_error}`;
  if (job.applied_at) return "Applied (unverified)";
  if (job.apply_attempts != null && job.apply_attempts > 0) {
    return `Attempted (${job.apply_attempts})`;
  }
  return "Not applied";
}
