/** Mirrors `start_apply_run` in run_controller.py for dashboard CLI previews. */

export type ApplyCliOptions = {
  limit: number | "";
  minScore: number;
  workers: number;
  watch: boolean;
  pace: boolean;
  headless: boolean;
  continuous: boolean;
  dryRun: boolean;
  engine?: "direct" | "claude";
};

export function buildApplyCliCommand(opts: ApplyCliOptions): string {
  const parts = ["applypilot", "apply", "--engine", opts.engine ?? "direct"];
  const limit = opts.limit === "" ? null : Number(opts.limit);
  if (limit != null && limit > 0) {
    parts.push("--limit", String(limit));
    if (!opts.continuous) parts.push("--no-continuous");
  } else {
    parts.push("--continuous");
  }
  parts.push("--min-score", String(opts.minScore), "--workers", String(opts.workers));
  if (opts.watch) parts.push("--watch");
  else if (opts.pace) parts.push("--pace", "2");
  if (opts.headless) parts.push("--headless");
  if (opts.dryRun) parts.push("--dry-run");
  return parts.join(" ");
}

export function applyRunSummaryLines(
  opts: ApplyCliOptions,
  readyCount?: number | string,
): string[] {
  const limit = opts.limit === "" ? null : Number(opts.limit);
  const lines = [
    readyCount != null ? `Ready queue: ${readyCount} (min score ≥${opts.minScore})` : `Min score ≥${opts.minScore}`,
    `${opts.workers} worker(s) · direct apply first (Claude rescue when needed)`,
    opts.watch
      ? "Visible Chrome (--watch, slow pacing)"
      : opts.headless
        ? "Headless browser"
        : "Visible Chrome (no --watch)",
    limit != null && limit > 0
      ? opts.continuous
        ? `Up to ${limit} jobs, then keep polling for more`
        : `Stop after ${limit} job(s)`
      : "Drain the queue (--continuous)",
  ];
  if (opts.dryRun) lines.push("Dry run only (no submissions)");
  return lines;
}

export type ApplyRunSettings = {
  limit: number | "";
  setLimit: (value: number | "") => void;
  minScore: number;
  setMinScore: (value: number) => void;
  workers: number;
  setWorkers: (value: number) => void;
  watch: boolean;
  setWatch: (value: boolean) => void;
  pace: boolean;
  setPace: (value: boolean) => void;
  headless: boolean;
  setHeadless: (value: boolean) => void;
  continuous: boolean;
  setContinuous: (value: boolean) => void;
  dryRun: boolean;
  setDryRun: (value: boolean) => void;
  isRunning?: boolean;
};

export function applySettingsToCliOptions(settings: ApplyRunSettings): ApplyCliOptions {
  return {
    limit: settings.limit,
    minScore: settings.minScore,
    workers: settings.workers,
    watch: settings.watch,
    pace: settings.pace,
    headless: settings.headless,
    continuous: settings.continuous,
    dryRun: settings.dryRun,
  };
}
