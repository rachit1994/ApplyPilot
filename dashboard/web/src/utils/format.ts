export function formatDuration(ms: number): string {
  if (ms < 0 || !Number.isFinite(ms)) return "—";
  const sec = Math.floor(ms / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function runDuration(run: {
  started_at: string | null;
  finished_at: string | null;
  status: string;
}): number | null {
  if (!run.started_at) return null;
  const start = new Date(run.started_at).getTime();
  const end = run.finished_at
    ? new Date(run.finished_at).getTime()
    : run.status === "running"
      ? Date.now()
      : null;
  if (end == null) return null;
  return end - start;
}

/** API returns source efficiency as a 0–1 ratio (scored_ge7 / discovered). */
export function sourceEfficiencyPercent(efficiency: number): number {
  if (!Number.isFinite(efficiency)) return 0;
  return Math.round(Math.max(0, Math.min(1, efficiency)) * 100);
}

export function formatTime(iso: string | null | undefined): string {
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
