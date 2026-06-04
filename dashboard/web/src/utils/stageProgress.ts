import type { RunEvent, Stats } from "../api";

export type StageProgressSnapshot = {
  stage?: string;
  done?: number;
  pending?: number;
  total?: number;
  percent?: number | null;
  detail?: string;
  waiting_upstream?: boolean;
};

export type StageState = "pending" | "active" | "done" | "error";

/** Latest stage_progress payload per stage (from run events). */
export function latestProgressByStage(events: RunEvent[]): Record<string, StageProgressSnapshot> {
  const map: Record<string, StageProgressSnapshot> = {};
  for (const e of events) {
    if (e.event_type !== "stage_progress" || !e.stage) continue;
    const payload = (e.payload ?? {}) as StageProgressSnapshot;
    map[e.stage] = { ...payload, stage: e.stage };
  }
  return map;
}

function snapshotFromStats(stage: string, stats: Stats, minScore: number): StageProgressSnapshot | null {
  const p = stats.pipeline ?? {};
  const total = stats.total ?? 0;

  switch (stage) {
    case "discover":
      return { stage, total, detail: `${total} jobs in database` };
    case "filter": {
      const kept = p.pre_filter_kept ?? 0;
      const rejected = p.pre_filter_rejected ?? 0;
      const done = kept + rejected;
      const pending = Math.max(0, total - done);
      const denom = done + pending;
      const percent = denom > 0 ? Math.round((100 * done) / denom) : null;
      return {
        stage,
        done,
        pending,
        total: denom,
        percent,
        detail: `${kept} kept · ${rejected} rejected · ${pending} waiting`,
      };
    }
    case "enrich": {
      const done = p.with_description ?? stats.with_description ?? 0;
      const pending = p.pending_detail ?? 0;
      const denom = total > 0 ? total : done + pending;
      const percent = denom > 0 ? Math.round((100 * done) / denom) : null;
      return {
        stage,
        done,
        pending,
        total: denom,
        percent,
        detail: `${done}/${denom} enriched · ${pending} left`,
      };
    }
    case "score": {
      const done = p.scored ?? stats.scored ?? 0;
      const pending = p.unscored ?? 0;
      const denom = done + pending;
      const percent = denom > 0 ? Math.round((100 * done) / denom) : null;
      return {
        stage,
        done,
        pending,
        total: denom,
        percent,
        detail: `${done} scored · ${pending} waiting`,
      };
    }
    case "tailor": {
      const done = p.tailored ?? stats.tailored ?? 0;
      const pending = p.untailored_eligible ?? 0;
      const denom = done + pending;
      const percent = denom > 0 ? Math.round((100 * done) / denom) : null;
      return {
        stage,
        done,
        pending,
        total: denom,
        percent,
        detail: `${done} tailored · ${pending} left (≥${minScore})`,
      };
    }
    case "cover": {
      const done = p.with_cover_letter ?? 0;
      const pending = Math.max(0, (stats.tailored ?? 0) - done);
      const denom = done + pending;
      const percent = denom > 0 ? Math.round((100 * done) / denom) : null;
      return {
        stage,
        done,
        pending,
        total: denom,
        percent,
        detail: `${done} cover letters · ${pending} left`,
      };
    }
    case "pdf": {
      const tailored = stats.tailored ?? 0;
      return {
        stage,
        total: tailored,
        detail: `${tailored} tailored resumes`,
      };
    }
    case "refer": {
      const sent = stats.extra?.referral_message_sent ?? 0;
      const pending = stats.extra?.referral_pending_connect ?? 0;
      return {
        stage,
        done: sent,
        pending,
        detail: `${sent} sent · ${pending} pending connect`,
      };
    }
    default:
      return null;
  }
}

export function resolveStageProgress(
  stage: string,
  state: StageState,
  eventProgress: StageProgressSnapshot | undefined,
  stats: Stats | undefined,
  minScore: number,
): StageProgressSnapshot | null {
  if (state === "pending") return null;
  if (eventProgress?.detail || eventProgress?.percent != null) {
    return eventProgress;
  }
  if (stats && (state === "active" || state === "done")) {
    return snapshotFromStats(stage, stats, minScore);
  }
  return eventProgress ?? null;
}

export function pipelineOverallProgress(
  stageOrder: string[],
  stageStates: Record<string, StageState>,
  activeProgress: StageProgressSnapshot | null,
): { completed: number; total: number; percent: number | null } {
  const total = stageOrder.length;
  if (total === 0) return { completed: 0, total: 0, percent: null };

  let completed = 0;
  let activeIndex = -1;
  stageOrder.forEach((s, i) => {
    const st = stageStates[s] ?? "pending";
    if (st === "done") completed += 1;
    if (st === "active") activeIndex = i;
  });

  const stageFraction = completed / total;
  let percent: number | null = Math.round(stageFraction * 100);
  if (activeIndex >= 0) {
    const slice = 100 / total;
    const inner =
      activeProgress?.percent != null
        ? Math.min(100, Math.max(0, activeProgress.percent)) / 100
        : 0.05;
    percent = Math.min(100, Math.round(completed * slice + inner * slice));
  }

  return { completed, total, percent };
}

export function formatStageProgressLine(snap: StageProgressSnapshot | null): string | null {
  if (!snap) return null;
  if (snap.detail) return snap.detail;
  if (snap.pending != null && snap.done != null) {
    return `${snap.done} done · ${snap.pending} remaining`;
  }
  if (snap.pending != null) return `${snap.pending} remaining`;
  return null;
}
