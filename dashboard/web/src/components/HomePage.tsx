import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchActiveRun, fetchStats, type Stats } from "../api";
import {
  PIPELINE_CARD_JOBS_STAGE,
  PIPELINE_STAGE_IDS,
  STAGE_DESCRIPTIONS,
  STAGE_LABELS,
  type PipelineStageId,
} from "../dashboardNav";
import { stagePendingLabel } from "../utils/stageCounts";
import { HomeRunBar } from "./HomeRunBar";
import { RunBanner } from "./RunBanner";
import { StatsRow } from "./StatsRow";

type Props = {
  onOpenJobs: (params?: Record<string, string>) => void;
  onOpenApplications?: (params?: Record<string, string>) => void;
};

export function HomePage({ onOpenJobs, onOpenApplications }: Props) {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const { data: activeRun } = useQuery({
    queryKey: ["runs", "active"],
    queryFn: fetchActiveRun,
    refetchInterval: 5000,
  });

  const pipeline = stats?.pipeline ?? {};
  const unverified = pipeline.submitted_unverified ?? 0;
  const extra = stats?.extra ?? {};

  const hero = useMemo(
    () => [
      {
        label: "Applied",
        value: stats?.applied ?? "—",
        onClick: () => onOpenJobs({ stage: "applied" }),
      },
      {
        label: "Needs verification",
        value: unverified,
        warn: unverified > 0,
        onClick: () =>
          onOpenApplications
            ? onOpenApplications({ filter: "unverified" })
            : onOpenJobs({ stage: "needs_check" }),
      },
      {
        label: "Ready to apply",
        value: stats?.ready_to_apply ?? pipeline.pending_apply ?? "—",
        onClick: () => onOpenJobs({ stage: "ready" }),
      },
      {
        label: "Total jobs",
        value: stats?.total ?? "—",
        onClick: () => onOpenJobs({}),
      },
      {
        label: "Spend today",
        value: formatSpend(extra.llm_cost_today ?? extra.cost_today ?? extra.spend_today),
      },
    ],
    [stats, unverified, pipeline.pending_apply, extra, onOpenJobs, onOpenApplications],
  );

  return (
    <div className="space-y-6 pb-8">
      <RunBanner run={activeRun ?? null} />

      {unverified > 0 ? (
        <button
          type="button"
          onClick={() =>
            onOpenApplications
              ? onOpenApplications({ filter: "unverified" })
              : onOpenJobs({ stage: "needs_check" })
          }
          className="w-full rounded-card border border-warn/50 bg-warn/10 px-4 py-3 text-left text-sm hover:bg-warn/15"
        >
          <strong className="text-warn">{unverified}</strong> ghost apply
          {unverified === 1 ? "" : "ies"} — submitted but not verified.{" "}
          {onOpenApplications ? "Review in Applications." : "View in Jobs."}
        </button>
      ) : null}

      {activeRun?.status === "failed" && activeRun.error_message ? (
        <div className="rounded-card border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">
          Last run failed: {activeRun.error_message}
        </div>
      ) : null}

      <section>
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-4">Health</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {hero.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={item.onClick}
              disabled={!item.onClick}
              className={`rounded-card border bg-panel p-4 text-left transition-colors ${
                item.onClick ? "hover:border-accent/40 hover:bg-panel-elevated" : ""
              } ${item.warn ? "border-warn/40" : "border-panel-border"}`}
            >
              <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
                {item.label}
              </p>
              <p
                className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${
                  item.warn ? "text-warn" : "text-accent"
                }`}
              >
                {item.value}
              </p>
            </button>
          ))}
        </div>
      </section>

      <StatsRow stats={stats} isLoading={isLoading} />

      <HomeRunBar />

      <section>
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-ink-4">
          Pipeline summary
        </h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {PIPELINE_STAGE_IDS.map((stage) => (
            <StageCard
              key={stage}
              stage={stage}
              stats={stats}
              active={activeRun?.current_stage === stage && activeRun?.status === "running"}
              onOpen={() =>
                onOpenJobs({ stage: PIPELINE_CARD_JOBS_STAGE[stage] })
              }
            />
          ))}
        </div>
      </section>

      <section className="rounded-card border border-panel-border bg-panel p-4">
        <h3 className="font-display text-sm text-ink">CLI equivalents</h3>
        <ul className="mt-2 space-y-1.5 font-mono text-xs text-ink-3">
          <li>applypilot run discover</li>
          <li>applypilot run enrich score tailor cover pdf</li>
          <li>applypilot apply --watch</li>
          <li>applypilot inbox scan — LinkedIn Other tab (CLI)</li>
        </ul>
      </section>
    </div>
  );
}

function StageCard({
  stage,
  stats,
  active,
  onOpen,
}: {
  stage: PipelineStageId;
  stats: Stats | undefined;
  active: boolean;
  onOpen: () => void;
}) {
  const pendingLabel = stagePendingLabel(stage, stats);

  return (
    <button
      type="button"
      onClick={onOpen}
      className={`rounded-card border bg-panel p-4 text-left transition-colors hover:border-accent/40 hover:bg-panel-elevated ${
        active ? "border-accent/50 ring-1 ring-accent/20" : "border-panel-border"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-base text-ink">{STAGE_LABELS[stage]}</span>
        {active ? (
          <span className="rounded-chip bg-accent/15 px-2 py-0.5 text-[10px] font-medium text-accent">
            running
          </span>
        ) : null}
      </div>
      <p className="mt-2 font-mono text-xs text-accent">{pendingLabel}</p>
      <p className="mt-2 text-xs leading-relaxed text-ink-3">{STAGE_DESCRIPTIONS[stage]}</p>
      <p className="mt-3 text-xs font-medium text-accent">View in Jobs →</p>
    </button>
  );
}

function formatSpend(raw: unknown): string {
  if (typeof raw === "number") return `$${raw.toFixed(2)}`;
  if (typeof raw === "string" && raw) return raw.startsWith("$") ? raw : `$${raw}`;
  return "—";
}
