import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPendingLogins, fetchStats, postResumeLogin } from "../api";
import { useApplyRun } from "../hooks/useApplyRun";
import { summarizeWorkers, workerStatusLabel, workerStatusbarClass } from "../utils/applyRunState";
import { ApplyRunControls } from "./ApplyRunControls";
import { ClaudeUsagePanel } from "./ClaudeUsagePanel";
import { LogConsole } from "./LogConsole";

type Props = {
  unverifiedCount?: number;
  onOpenApplications?: (params?: Record<string, string>) => void;
};

export function ApplyPage({ unverifiedCount = 0, onOpenApplications }: Props) {
  const run = useApplyRun();
  const queryClient = useQueryClient();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });
  const { data: loginState } = useQuery({
    queryKey: ["login-pending"],
    queryFn: fetchPendingLogins,
    refetchInterval: run.isRunning ? 3000 : 10000,
  });
  const resumeLogin = useMutation({
    mutationFn: (domain?: string) => postResumeLogin(domain),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["login-pending"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const pipeline = stats?.pipeline ?? {};
  const unverified = unverifiedCount ?? pipeline.submitted_unverified ?? 0;
  const appliedCount = stats?.applied ?? 0;
  const agent = run.agentState;
  const workerSummary = useMemo(
    () => summarizeWorkers(run.workerSnapshots),
    [run.workerSnapshots],
  );
  const pendingLogins = loginState?.pending ?? [];

  return (
    <>
      <section className="runband apply-runband" aria-label="Apply Queue">
        <div className="runband__status">
          {agent.pulse ? <span className="runband__pulse" aria-hidden /> : null}
          <div>
            <div className="runband__label">
              <span className={agent.statusbarClassName}>{agent.label}</span>
            </div>
            <div className="runband__title">Apply agent</div>
            <div className="runband__sub">{agent.subtitle}</div>
            {run.error || run.activeRun?.error_message ? (
              <div className="runband__sub" style={{ color: "var(--warn)", marginTop: 6 }}>
                {run.error ?? run.activeRun?.error_message}
              </div>
            ) : null}
          </div>
        </div>
        <div className="runband__controls">
          <button
            type="button"
            className="btn btn--accent"
            disabled={run.isRunning || run.starting}
            onClick={() => void run.handleStart()}
          >
            {run.starting ? "Starting…" : "Run apply"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!run.isRunning}
            onClick={() => void run.handleStop()}
          >
            Stop
          </button>
          {onOpenApplications ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => onOpenApplications(unverified > 0 ? { filter: "unverified" } : undefined)}
            >
              Review applications
            </button>
          ) : null}
        </div>
        <div className="runband__metrics">
          <div className="kpi">
            <div className="kpi__label">Ready</div>
            <div className="kpi__value">{stats?.ready_to_apply ?? "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Applied</div>
            <div className="kpi__value">{appliedCount ?? "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Unverified</div>
            <div className="kpi__value">{unverified ?? "—"}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Errors</div>
            <div className="kpi__value">{run.errors.length}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">Workers</div>
            <div className="kpi__value">{run.workers}</div>
          </div>
        </div>
      </section>

      <section className="kpis apply-kpis" aria-label="Apply KPIs">
        <div className="kpi">
          <div className="kpi__label">Ready to apply</div>
          <div className="kpi__value">{stats?.ready_to_apply ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Applied today</div>
          <div className="kpi__value">{appliedCount ?? "—"}</div>
        </div>
        <div className={`kpi ${unverified > 0 ? "kpi--attn" : ""}`}>
          <div className="kpi__label">Needs verify</div>
          <div className="kpi__value">{unverified ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Failed</div>
          <div className="kpi__value">{pipeline.apply_errors ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Worker count</div>
          <div className="kpi__value">{run.workers}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">Mode</div>
          <div className="kpi__value">{run.watch ? "watch" : run.headless ? "headless" : "visible"}</div>
        </div>
      </section>

      <ClaudeUsagePanel compact className="apply-claude-usage" />

      {pendingLogins.length > 0 ? (
        <section className="panel apply-login-gate" aria-label="Pending logins">
          <div className="panel__head">
            <div>
              <div className="panel__title">Awaiting login</div>
              <div className="panel__sub">
                Sign in inside the visible Chrome window, then resume this domain.
              </div>
            </div>
          </div>
          <div className="panel__body">
            <div className="grid gap-8">
              {pendingLogins.map((item) => {
                const noGoogle = item.reason === "login_required_no_google";
                return (
                  <div key={item.domain} className="login-gate-row">
                    <div className="min-w-0">
                      <div className="login-gate-row__title">{item.domain}</div>
                      <div className="login-gate-row__meta">
                        {noGoogle ? "No Google sign-in shown" : "Login required"}
                        {item.url ? ` · ${item.url}` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn--accent btn--sm"
                      disabled={resumeLogin.isPending}
                      onClick={() => resumeLogin.mutate(item.domain)}
                    >
                      Resume
                    </button>
                  </div>
                );
              })}
            </div>
            {pendingLogins.length > 1 ? (
              <div className="mt-10">
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={resumeLogin.isPending}
                  onClick={() => resumeLogin.mutate(undefined)}
                >
                  Resume all
                </button>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="panel apply-controls" aria-label="Run controls">
        <div className="panel__head">
          <div>
            <div className="panel__title">Run controls</div>
            <div className="panel__sub">Visible Chrome by default · use watch + pace</div>
          </div>
        </div>
        <div className="panel__body">
          <div className="panel__meta font-mono text-xs">{run.applyCli}</div>

          <ApplyRunControls settings={run.applySettings} />
        </div>
      </section>

      <section className="panel inbox apply-workers" aria-label="Apply workers">
        <div className="panel__head">
          <div>
            <div className="panel__title">Workers</div>
            <div className="panel__sub">{workerSummary}</div>
          </div>
        </div>
        <div className="panel__body--tight">
          {run.workerSnapshots.length === 0 ? (
            <div className="p-16 text-center text-sm text-ink-3">
              {run.isRunning || run.starting
                ? "Waiting for worker heartbeats…"
                : "Start apply to see worker status."}
            </div>
          ) : (
            <div className="grid gap-8 sm:grid-cols-2">
              {run.workerSnapshots.map((worker) => (
                <div key={worker.workerId} className="worker">
                  <div className="worker__ring">
                    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
                      <circle className="worker__ring-bg" cx="14" cy="14" r="12" />
                      <circle className="worker__ring-fg" cx="14" cy="14" r="12" />
                    </svg>
                  </div>
                  <div className="worker__name">Worker {worker.workerId}</div>
                  <div className="worker__stat">
                    <span className={workerStatusbarClass(worker.status)}>
                      {workerStatusLabel(worker.status)}
                    </span>
                  </div>
                  <div className="worker__stat">{worker.detail || "—"}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="panel feed apply-logs" aria-label="Apply logs">
        <div className="panel__head">
          <div>
            <div className="panel__title">Activity</div>
            <div className="panel__sub">
              {run.isRunning ? "Live" : agent.phase === "idle" ? "Idle" : agent.label} · {run.events.length}{" "}
              events
            </div>
          </div>
        </div>
        <div className="panel__body--tight">
          <div className="scroll-thin max-h-[72vh] overflow-auto">
            <LogConsole events={run.events} errors={run.errors} />
          </div>
        </div>
      </section>
    </>
  );
}
