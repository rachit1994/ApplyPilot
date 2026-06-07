import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApplications, fetchOverview, fetchStats, stopRun } from "../api";
import { useHomeRuns } from "../hooks/useHomeRuns";
import { needsHumanIntervention } from "../utils/applicationAudit";
import {
  buildDevlogRowsFromRunEvents,
  devlogRowFromActivity,
  formatDevlogLocalTime,
  type DevlogRow,
} from "../utils/devlog";
import { parseScoreGe8Subtitle } from "../utils/jobTriage";
import { PageCanvas } from "./layout/PageCanvas";
import { PipelineRunPlanModal } from "./PipelineRunPlanModal";

type Props = {
  onOpenJobs: (params?: Record<string, string>) => void;
  onOpenApplications?: (params?: Record<string, string>) => void;
  onOpenOutreach?: () => void;
};

function displayCount(value: number): string {
  return String(value);
}

type DevlogFilter = "all" | "errors" | "discover" | "score" | "apply" | "outreach";

function matchesDevlogFilter(row: DevlogRow, filter: DevlogFilter): boolean {
  if (filter === "all") return true;
  if (filter === "errors") return row.level === "error";
  const stage = row.stage.toLowerCase();
  const message = row.message.toLowerCase();
  if (filter === "discover") {
    return stage === "discover" || message.includes("discover") || message.includes("naukri");
  }
  if (filter === "score") {
    return stage === "score" || stage === "enrich" || message.includes("score");
  }
  if (filter === "apply") {
    return stage === "apply" || stage === "pdf" || stage === "tailor" || message.includes("apply");
  }
  if (filter === "outreach") {
    return stage === "refer" || stage === "cover" || message.includes("refer") || message.includes("outreach");
  }
  return true;
}

export function HomePage({ onOpenJobs, onOpenApplications, onOpenOutreach }: Props) {
  const queryClient = useQueryClient();
  const runControl = useHomeRuns();
  const [devlogOpen, setDevlogOpen] = useState(false);
  const [devlogFilter, setDevlogFilter] = useState<DevlogFilter>("all");
  const [pipelinePlanOpen, setPipelinePlanOpen] = useState(false);
  const devlogListRef = useRef<HTMLDivElement>(null);
  const devlogStickRef = useRef(true);

  const { data: overview } = useQuery({
    queryKey: ["overview"],
    queryFn: fetchOverview,
    refetchInterval: 5000,
  });

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
    refetchInterval: false,
    staleTime: 15_000,
  });

  const { data: manualApps } = useQuery({
    queryKey: ["applications", "manual-preview"],
    queryFn: () =>
      fetchApplications({
        limit: 5,
        include_failed: true,
        status: undefined,
      }),
    refetchInterval: false,
    staleTime: 60_000,
  });

  const pipeline = stats?.pipeline ?? {};
  const unverified = overview?.kpis.needs_verify ?? pipeline.submitted_unverified ?? 0;
  const discoveredHint = overview?.kpis.pipeline_total_subtitle ?? "";
  const discoveredToday = discoveredHint.startsWith("+")
    ? Number(discoveredHint.replace(/[^\d]/g, "")) || 0
    : 0;
  const scoreGe8 = parseScoreGe8Subtitle(overview?.kpis.ready_to_apply_subtitle);
  const newJobsCount =
    discoveredToday ||
    overview?.kpis.pipeline_total ||
    (pipeline.scored ?? 0) + (pipeline.unscored ?? 0) ||
    stats?.scored ||
    0;
  const outreachReady =
    stats?.extra?.inbox_queue ??
    stats?.extra?.outreach_queue ??
    stats?.extra?.referral_pending_connect ??
    0;
  const manualTotal = Math.max(
    unverified,
    manualApps?.applications?.filter(needsHumanIntervention).length ?? 0,
    unverified > 0 ? unverified : 0,
  );
  const dmsSent = stats?.extra?.referral_message_sent ?? 0;

  const manualRows = useMemo(() => {
    return (manualApps?.applications ?? []).filter(needsHumanIntervention).slice(0, 3);
  }, [manualApps?.applications]);

  const steps = overview?.runband.steps ?? [];
  const activeIndex = steps.findIndex((s) => s.state === "active");
  const activeStep = activeIndex >= 0 ? steps[activeIndex] : undefined;
  const progressPct =
    activeStep?.percent ??
    (activeStep?.total && activeStep.done != null
      ? Math.round((activeStep.done / activeStep.total) * 100)
      : null);

  const handleStop = useCallback(async () => {
    if (runControl.activeRun?.id) {
      await runControl.handleStop();
      return;
    }
    const id = overview?.runband.run_id;
    if (!id) return;
    await stopRun(id);
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  }, [overview?.runband.run_id, queryClient, runControl]);

  const activity = overview?.activity ?? [];
  const caps = overview?.caps;

  const devlogSource = useMemo(() => {
    const fromRun = buildDevlogRowsFromRunEvents(runControl.events);
    if (fromRun.length > 0) {
      return fromRun.slice(-500);
    }
    return activity.map(devlogRowFromActivity);
  }, [runControl.events, activity]);

  const devlogRows = useMemo(
    () => devlogSource.filter((row) => matchesDevlogFilter(row, devlogFilter)),
    [devlogSource, devlogFilter],
  );

  const activityCounts = useMemo(() => {
    let ok = 0;
    let warn = 0;
    let err = 0;
    for (const ev of devlogSource) {
      if (ev.level === "error") err += 1;
      else if (ev.level === "warn") warn += 1;
      else ok += 1;
    }
    return { ok, warn, err };
  }, [devlogSource]);

  const isRunning = runControl.isRunning || overview?.runband.status === "running";

  useEffect(() => {
    if (isRunning) setDevlogOpen(true);
  }, [isRunning]);

  useEffect(() => {
    const el = devlogListRef.current;
    if (!el || !devlogStickRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [devlogRows.length, devlogOpen]);

  const onDevlogScroll = useCallback(() => {
    const el = devlogListRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    devlogStickRef.current = distance <= 80;
  }, []);
  const nextActionCount = manualRows.length || manualTotal || unverified;
  const manualViewAll = manualTotal || unverified || manualRows.length;
  const scoreSub =
    scoreGe8 != null
      ? `${scoreGe8} are score 8 or higher`
      : newJobsCount > 0
        ? "Run discover to refresh"
        : "0 are score 8 or higher";

  return (
    <PageCanvas>
      <div className="today">
        <div className="today__hero">
          <button type="button" className="summary summary--primary" onClick={() => onOpenJobs({})}>
            <div className="summary__icon">
              <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <rect x="2" y="5" width="14" height="10" rx="1.5" />
                <path d="M6 5V3.5a1 1 0 011-1h4a1 1 0 011 1V6" />
              </svg>
            </div>
            <div className="summary__count">{displayCount(newJobsCount)}</div>
            <div className="summary__label">New jobs match you</div>
            <div className="summary__sub">{scoreSub}</div>
            <div className="summary__cta">
              Triage now
              <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden>
                <path d="m5 3 4 4-4 4" />
              </svg>
            </div>
          </button>

          <button
            type="button"
            className="summary summary--warn"
            onClick={() =>
              onOpenApplications
                ? onOpenApplications({ filter: "needs_action" })
                : onOpenJobs({ stage: "needs_check" })
            }
          >
            <div className="summary__icon">
              <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M9 2 2 15h14L9 2z" />
                <path d="M9 7v3M9 12.5v.5" />
              </svg>
            </div>
            <div className="summary__count">{displayCount(manualTotal)}</div>
            <div className="summary__label">Need your apply</div>
            <div className="summary__sub">Auto-apply hit a wall — your move</div>
            <div className="summary__cta" style={{ color: "var(--warn)" }}>
              Review
              <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden>
                <path d="m5 3 4 4-4 4" />
              </svg>
            </div>
          </button>

          <button
            type="button"
            className="summary"
            onClick={() => (onOpenOutreach ? onOpenOutreach() : onOpenJobs({}))}
          >
            <div className="summary__icon">
              <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="m16 2-7 7" />
                <path d="M16 2 10 16l-1-7-7-1L16 2z" />
              </svg>
            </div>
            <div className="summary__count">{displayCount(outreachReady)}</div>
            <div className="summary__label">Outreach ready to send</div>
            <div className="summary__sub">LinkedIn drafts for hiring managers</div>
            <div className="summary__cta">
              Send
              <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden>
                <path d="m5 3 4 4-4 4" />
              </svg>
            </div>
          </button>
        </div>

        {nextActionCount > 0 ? (
          <div className="next-action">
            <div className="next-action__icon">
              <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <circle cx="11" cy="11" r="8" />
                <path d="m8 11 2 2 4-4" />
              </svg>
            </div>
            <div className="next-action__body">
              <div className="next-action__title">
                Apply to {nextActionCount} jobs the agent couldn&apos;t reach
              </div>
              <div className="next-action__sub">
                Workday SSO, CAPTCHA, and one form with unknown fields. Should take five minutes.
              </div>
            </div>
            <button
              type="button"
              className="btn btn--accent btn--lg"
              onClick={() =>
                onOpenApplications
                  ? onOpenApplications({ filter: "needs_action" })
                  : onOpenJobs({ stage: "needs_check" })
              }
            >
              Open list
            </button>
          </div>
        ) : null}

        <div>
          <div className="section-title">Right now</div>
          <div className="run-card">
            <div className="run-card__status">
              <div className="run-card__pulse" aria-hidden="true" />
              <div>
                <div className="run-card__title">{overview?.runband.title ?? "Ready"}</div>
                <div className="run-card__sub">{overview?.runband.subtitle ?? "No active run"}</div>
              </div>
            </div>
            <div className="run-card__progress">
              <div className="run-card__bar">
                <div
                  className="run-card__bar-fill"
                  style={progressPct != null ? { width: `${progressPct}%`, animation: "none" } : undefined}
                />
              </div>
              <div className="run-card__bar-label">
                <span>
                  {activeIndex >= 0 && steps.length > 0 ? (
                    <>
                      Stage <strong>{activeIndex + 1}</strong> of {steps.length} · {activeStep?.label ?? "—"}
                    </>
                  ) : (
                    <>
                      Stage <strong>{activeStep?.label ?? "—"}</strong>
                    </>
                  )}
                </span>
                <span>{progressPct != null ? `${progressPct}%` : "—"}</span>
              </div>
            </div>
            {isRunning ? (
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void handleStop()}>
                Pause
              </button>
            ) : (
              <button
                type="button"
                className="btn btn--accent btn--sm"
                disabled={runControl.starting}
                onClick={() => setPipelinePlanOpen(true)}
              >
                {runControl.starting ? "Starting…" : "New run"}
              </button>
            )}
          </div>
        </div>

        <div>
          <div className="section-row">
            <div className="section-title" style={{ marginBottom: 0 }}>
              Need your apply
            </div>
            {manualViewAll > 0 ? (
              <button
                type="button"
                className="summary__cta"
                style={{ marginTop: 0 }}
                onClick={() =>
                  onOpenApplications
                    ? onOpenApplications({ filter: "needs_action" })
                    : onOpenJobs({ stage: "needs_check" })
                }
              >
                View all {manualViewAll}
                <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden>
                  <path d="m5 3 4 4-4 4" />
                </svg>
              </button>
            ) : null}
          </div>
          <div className="panel">
            {manualRows.length > 0 ? (
              manualRows.map((row) => (
                <div key={row.url} className="manual-row">
                  <span className="statusbar statusbar--warn">Manual</span>
                  <div className="manual-row__main">
                    <div className="manual-row__title">{row.title ?? "Untitled"}</div>
                    <div className="manual-row__company">
                      {row.site ?? "—"} · {row.apply_status ?? "needs action"}
                    </div>
                  </div>
                  <div className="manual-row__reason">{row.apply_error ?? "Needs review"}</div>
                  {row.url ? (
                    <a className="btn btn--sm btn--accent" href={row.url} target="_blank" rel="noreferrer">
                      Apply now
                    </a>
                  ) : (
                    <button type="button" className="btn btn--sm btn--accent">
                      Apply now
                    </button>
                  )}
                </div>
              ))
            ) : (
              <div className="manual-row">
                <span className="statusbar statusbar--warn">Manual</span>
                <div className="manual-row__main">
                  <div className="manual-row__title">No manual queue right now</div>
                  <div className="manual-row__company">Auto-apply is caught up on reachable forms</div>
                </div>
                <div className="manual-row__reason" />
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="section-title">Yesterday</div>
          <div className="recap">
            <div className="recap__item">
              <div className="recap__num">{displayCount(caps?.apply_today ?? 0)}</div>
              <div className="recap__label">Applied automatically</div>
            </div>
            <div className="recap__item">
              <div className="recap__num">{unverified}</div>
              <div className="recap__label">Manual fallback</div>
            </div>
            <div className="recap__item">
              <div className="recap__num">{dmsSent}</div>
              <div className="recap__label">DMs sent</div>
            </div>
            <div className="recap__item">
              <div className="recap__num">${(caps?.spend_today_usd ?? 0).toFixed(2)}</div>
              <div className="recap__label">Spent</div>
            </div>
          </div>
        </div>

        <div className={devlogOpen ? "devlog devlog--open" : "devlog"} id="devlog">
          <button
            type="button"
            className="devlog__head"
            onClick={() => setDevlogOpen((v) => !v)}
            aria-expanded={devlogOpen}
          >
            <div className="devlog__title">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" aria-hidden>
                <path d="m5 4 4 4-4 4" />
              </svg>
              Developer log
            </div>
            <div className="devlog__meta">
              <span>
                <span className="dot dot--ok" />
                {activityCounts.ok} ok
              </span>
              <span>
                <span className="dot dot--warn" />
                {activityCounts.warn} warn
              </span>
              <span>
                <span className="dot" style={{ background: "#ff8a8a" }} />
                {activityCounts.err} err
              </span>
              <span>
                {isRunning
                  ? `live · ${devlogSource.length} lines`
                  : devlogSource.length > 0
                    ? `${devlogSource.length} lines`
                    : "last 24h"}
              </span>
            </div>
          </button>
          {devlogOpen ? (
            <div className="devlog__body">
              <div className="devlog__bar">
                {(
                  [
                    ["all", "All"],
                    ["errors", "Errors"],
                    ["discover", "Discover"],
                    ["score", "Score"],
                    ["apply", "Apply"],
                    ["outreach", "Outreach"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={devlogFilter === id ? "chip chip--on" : "chip"}
                    onClick={() => setDevlogFilter(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="devlog__list" ref={devlogListRef} onScroll={onDevlogScroll}>
                {devlogRows.length === 0 ? (
                  <div className="devlog__row">
                    <span className="devlog__time">—</span>
                    <span className="devlog__stage">—</span>
                    <span className="devlog__link">—</span>
                    <span className="devlog__msg">
                      {isRunning
                        ? "Waiting for log lines from the active run…"
                        : "No recent activity yet. Start a run to stream logs here."}
                    </span>
                  </div>
                ) : (
                  devlogRows.map((ev) => (
                    <div
                      key={ev.id}
                      className={
                        ev.level === "error"
                          ? "devlog__row devlog__row--err"
                          : ev.level === "warn"
                            ? "devlog__row devlog__row--warn"
                            : "devlog__row"
                      }
                    >
                      <span className="devlog__time">{formatDevlogLocalTime(ev.ts)}</span>
                      <span className="devlog__stage">{ev.stage}</span>
                      <span className="devlog__link">
                        {ev.jobUrl ? (
                          <a href={ev.jobUrl} target="_blank" rel="noopener noreferrer">
                            link
                          </a>
                        ) : (
                          "—"
                        )}
                      </span>
                      <span className="devlog__msg">{ev.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <PipelineRunPlanModal
        open={pipelinePlanOpen}
        settings={{
          stageOrder: runControl.stageOrder,
          selectedStages: runControl.selectedStages,
          toggleStage: runControl.toggleStage,
          setSelectedStages: runControl.setSelectedStages,
          stream: runControl.stream,
          setStream: runControl.setStream,
          dryRun: runControl.dryRun,
          setDryRun: runControl.setDryRun,
          pipelineMinScore: runControl.pipelineMinScore,
          setPipelineMinScore: runControl.setPipelineMinScore,
          workers: runControl.workers,
          setWorkers: runControl.setWorkers,
          isRunning: runControl.isRunning,
        }}
        onCancel={() => setPipelinePlanOpen(false)}
        onConfirm={() => {
          setPipelinePlanOpen(false);
          void runControl.handleStartPipeline();
        }}
      />
    </PageCanvas>
  );
}
