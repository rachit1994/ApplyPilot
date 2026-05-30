import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "../api";
import { PIPELINE_STAGE_IDS } from "../dashboardNav";
import { useApplyRun } from "../hooks/useApplyRun";
import { useHomeRuns } from "../hooks/useHomeRuns";
import { ClaudeUsagePanel } from "./ClaudeUsagePanel";
import { PageCanvas } from "./layout/PageCanvas";

export function PipelineDashboardPage() {
  const runControl = useHomeRuns();
  const applyRun = useApplyRun();

  const { data: overview } = useQuery({
    queryKey: ["overview"],
    queryFn: fetchOverview,
    refetchInterval: 5000,
  });

  const runband = overview?.runband;
  const isRunning = runControl.isRunning || runband?.status === "running";

  const funnel = overview?.funnel ?? [];
  const sources = overview?.sources ?? [];
  const caps = overview?.caps;

  return (
    <PageCanvas wide>
      <div className="pipeline">
        <div className="runband">
          <div className="runband__status">
            <div className="runband__pulse" aria-hidden={!isRunning} />
            <div>
              <div className="runband__label">{isRunning ? "Running" : "Ready"}</div>
              <div className="runband__title">{runband?.title ?? "Pipeline"}</div>
              <div className="runband__sub">{runband?.subtitle ?? "Start a discover → tailor run"}</div>
            </div>
          </div>

          <div className="stepper">
            {(runband?.steps?.length ? runband.steps : defaultSteps()).map((step) => (
              <div
                key={step.id}
                className={
                  step.state === "active"
                    ? "step step--active"
                    : step.state === "done"
                      ? "step step--done"
                      : "step step--pending"
                }
              >
                <div className="step__label">{step.label}</div>
                <div className="step__bar">
                  <div
                    className="step__bar-fill"
                    style={
                      step.state === "done"
                        ? { width: "100%" }
                        : step.percent != null
                          ? { width: `${step.percent}%`, animation: "none" }
                          : undefined
                    }
                  />
                </div>
                <div className="step__count">
                  {step.count_text ? (
                    <span dangerouslySetInnerHTML={{ __html: step.count_text }} />
                  ) : (
                    <>
                      {step.done != null && step.total != null ? (
                        <>
                          <strong>{step.done}</strong>/{step.total}
                        </>
                      ) : (
                        step.detail ?? "queued"
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="runband__controls">
            <button
              type="button"
              className="btn btn--ghost"
              disabled={!isRunning && !applyRun.isRunning}
              onClick={() =>
                void (applyRun.isRunning ? applyRun.handleStop() : runControl.handleStop())
              }
            >
              Pause
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={applyRun.isRunning || applyRun.starting}
              onClick={() => void applyRun.handleStart()}
            >
              {applyRun.starting ? "Starting…" : "Apply queue now"}
            </button>
            <button
              type="button"
              className="btn btn--accent"
              disabled={runControl.starting || runControl.pipelineStartRequested || isRunning}
              onClick={() => void runControl.handleStartPipeline()}
            >
              {runControl.starting ? "Starting…" : "New run"}
            </button>
          </div>
        </div>

        <div className="pipeline__grid">
          <div className="panel">
            <div className="panel__head panel__head--inset">
              <div>
                <div className="panel__title">Funnel</div>
                <div className="panel__sub">{overview?.funnel_subtitle ?? "Pipeline funnel"}</div>
              </div>
            </div>
            <div className="panel__body">
              <div className="funnel__rows">
                {funnel.length === 0 ? (
                  <p className="panel__sub">No funnel data yet.</p>
                ) : (
                  funnel.map((row, i) => {
                    const width = funnel[0]?.count
                      ? Math.max(4, Math.round((row.count / funnel[0].count) * 100))
                      : 0;
                    const dim = i >= funnel.length - 2;
                    return (
                      <div key={row.id} className="fnl">
                        <div className="fnl__name">{row.label}</div>
                        <div className="fnl__bar">
                          <div
                            className={dim ? "fnl__bar-fill fnl__bar-fill--dim" : "fnl__bar-fill"}
                            style={{ width: `${width}%`, minWidth: width > 0 ? 4 : 0 }}
                          />
                        </div>
                        <div className="fnl__count">{row.count}</div>
                        <div className="fnl__rate">
                          {row.rate_percent != null ? `${row.rate_percent}%` : "—"}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel__head panel__head--inset">
              <div>
                <div className="panel__title">Sources</div>
                <div className="panel__sub">Score ≥ 7 / discovered</div>
              </div>
            </div>
            <div className="panel__body panel__body--tight">
              {sources.length === 0 ? (
                <p className="panel__sub" style={{ padding: 12 }}>
                  No source stats yet.
                </p>
              ) : (
                sources.map((src) => (
                  <div key={src.source} className="src-row">
                    <div className="src__name">
                      {src.source} <small>{src.discovered} jobs</small>
                    </div>
                    <div className="src__meter">
                      <div
                        className={
                          src.efficiency < 50 ? "src__meter-fill src__meter-fill--dim" : "src__meter-fill"
                        }
                        style={{ width: `${Math.round(src.efficiency)}%` }}
                      />
                    </div>
                    <div className={src.efficiency < 50 ? "src__eff src__eff--dim" : "src__eff"}>
                      {Math.round(src.efficiency)}%
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel__head panel__head--inset">
              <div>
                <div className="panel__title">Caps & spend</div>
                <div className="panel__sub">Today · resets at midnight</div>
              </div>
            </div>
            <div className="panel__body panel__body--tight">
              <CapRow
                label="LLM spend"
                value={`$${(caps?.spend_today_usd ?? 0).toFixed(2)}`}
                used={caps?.spend_today_usd ?? 0}
                cap={caps?.spend_cap_usd}
              />
              <CapRow
                label="Auto-apply"
                value={String(caps?.apply_today ?? 0)}
                used={caps?.apply_today ?? 0}
                cap={caps?.apply_cap}
              />
              <CapRow
                label="Resume tailoring"
                value={String(caps?.tailor_today ?? 0)}
                used={caps?.tailor_today ?? 0}
                cap={caps?.tailor_cap}
              />
            </div>
          </div>
        </div>

        <ClaudeUsagePanel className="pipeline__claude-usage" />
      </div>
    </PageCanvas>
  );
}

function CapRow({
  label,
  value,
  used,
  cap,
}: {
  label: string;
  value: string;
  used: number;
  cap?: number;
}) {
  const pct =
    cap != null && cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  return (
    <div className="cost__row">
      <div className="cost__row-top">
        <div className="cost__label">{label}</div>
        <div className="cost__value">
          {value}
          {cap != null ? <small>/ {cap}</small> : null}
        </div>
      </div>
      <div className="cost__bar">
        <div className="cost__bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function defaultSteps() {
  return PIPELINE_STAGE_IDS.map((id) => ({
    id,
    label: id.charAt(0).toUpperCase() + id.slice(1),
    done: null,
    pending: null,
    total: null,
    percent: null,
    detail: "queued",
    count_text: null as string | null,
    state: "pending" as const,
  }));
}
