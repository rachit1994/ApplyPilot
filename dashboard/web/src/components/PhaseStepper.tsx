import { useEffect, useMemo, useState, type ReactElement } from "react";
import type { RunEvent } from "../api";
import { formatDuration } from "../utils/format";

type StageState = "pending" | "active" | "done" | "error";

type Props = {
  stageOrder: string[];
  stageMeta: Record<string, { desc: string }>;
  stageStates: Record<string, StageState>;
  events?: RunEvent[];
};

const STAGE_ICONS: Record<string, (props: { className?: string }) => ReactElement> = {
  discover: IconSearch,
  enrich: IconDoc,
  score: IconStar,
  tailor: IconScissors,
  cover: IconMail,
  pdf: IconPdf,
};

function IconSearch({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
    </svg>
  );
}

function IconDoc({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  );
}

function IconStar({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.563.563 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
    </svg>
  );
}

function IconScissors({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m7.848 8.25 1.536 1.536M21 12l-9.75-9.75-3.75 3.75M3 21l9.75-9.75-3.75-3.75" />
    </svg>
  );
}

function IconMail({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75" />
    </svg>
  );
}

function IconPdf({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  );
}

function IconDefault({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
    </svg>
  );
}

function stateRing(state: StageState): string {
  switch (state) {
    case "active":
      return "border-blue-500/60 bg-blue-500/10 text-blue-200 shadow-[0_0_20px_-4px_rgba(59,130,246,0.4)]";
    case "done":
      return "border-emerald-600/50 bg-emerald-950/30 text-emerald-200";
    case "error":
      return "border-red-600/50 bg-red-950/30 text-red-200";
    default:
      return "border-zinc-700/80 bg-zinc-900/40 text-zinc-500";
  }
}

function connectorClass(leftState: StageState, _rightState: StageState): string {
  if (leftState === "done") return "bg-emerald-600/60";
  if (leftState === "active") return "bg-blue-500/50";
  return "bg-zinc-700/60";
}

export function PhaseStepper({ stageOrder, stageMeta, stageStates, events = [] }: Props) {
  const [, tick] = useState(0);

  const stageStartedAt = useMemo(() => {
    const map: Record<string, number> = {};
    for (const e of events) {
      if (e.event_type === "stage_start" && e.stage && e.created_at) {
        map[e.stage] = new Date(e.created_at).getTime();
      }
    }
    return map;
  }, [events]);

  const hasActive = stageOrder.some((s) => stageStates[s] === "active");

  useEffect(() => {
    if (!hasActive) return;
    const id = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [hasActive]);

  if (stageOrder.length === 0) return null;

  return (
    <section className="panel p-4">
      <h2 className="panel-title mb-4">Pipeline</h2>
      <ol className="flex flex-row items-start gap-0 overflow-x-auto">
        {stageOrder.map((stage, i) => {
          const state = stageStates[stage] ?? "pending";
          const Icon = STAGE_ICONS[stage] ?? IconDefault;
          const started = stageStartedAt[stage];
          const elapsed =
            state === "active" && started
              ? formatDuration(Date.now() - started)
              : null;
          const prevState = i > 0 ? (stageStates[stageOrder[i - 1]] ?? "pending") : "pending";

          return (
            <li key={stage} className="flex flex-1 flex-col items-stretch sm:min-w-0">
              <div className="flex items-center sm:flex-col sm:items-center">
                {i > 0 && (
                  <div
                    className={`hidden h-0.5 flex-1 sm:block sm:h-0.5 sm:w-full ${connectorClass(prevState, state)}`}
                    aria-hidden
                  />
                )}
                <div
                  title={stageMeta[stage]?.desc ?? stage}
                  className={`relative z-10 flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 sm:w-auto sm:min-w-[7rem] sm:flex-col sm:px-3 sm:py-3 ${stateRing(state)}`}
                >
                  <Icon className="h-5 w-5 shrink-0 opacity-90" />
                  <div className="min-w-0 text-center">
                    <div className="text-sm font-semibold capitalize">{stage}</div>
                    <div className="text-[10px] uppercase tracking-wide opacity-70">
                      {state === "active" && elapsed ? elapsed : state}
                    </div>
                  </div>
                  {state === "active" && (
                    <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-blue-400 animate-pulse" />
                  )}
                </div>
              </div>
              {i < stageOrder.length - 1 && (
                <div
                  className={`mx-auto mt-2 h-0.5 w-full max-w-[80%] ${connectorClass(state, stageStates[stageOrder[i + 1]] ?? "pending")}`}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
