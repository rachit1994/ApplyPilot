import { useQuery } from "@tanstack/react-query";
import { fetchLlmUsage } from "../api";

type Props = {
  compact?: boolean;
  className?: string;
};

export function ClaudeUsagePanel({ compact = false, className = "" }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["llm-usage"],
    queryFn: () => fetchLlmUsage(),
    refetchInterval: 15_000,
  });

  const summary = data?.summary;
  const config = data?.apply_config;
  const quota = data?.quota;

  if (isLoading) {
    return (
      <section className={`panel claude-usage ${className}`.trim()}>
        <div className="panel__body">
          <p className="panel__sub">Loading Claude usage…</p>
        </div>
      </section>
    );
  }

  if (isError || !data) {
    return (
      <section className={`panel claude-usage ${className}`.trim()}>
        <div className="panel__body">
          <p className="panel__sub">Could not load Claude usage ledger.</p>
        </div>
      </section>
    );
  }

  if (!data.ledger_available) {
    return (
      <section className={`panel claude-usage ${className}`.trim()}>
        <div className="panel__head panel__head--inset">
          <div>
            <div className="panel__title">Claude Code usage</div>
            <div className="panel__sub">No usage ledger yet</div>
          </div>
        </div>
        <div className="panel__body">
          <p className="panel__sub">
            Run apply, score, or tailor once — events are stored locally in{" "}
            <code>llm_usage_events</code>.
          </p>
        </div>
      </section>
    );
  }

  const models = data.by_model_month ?? [];
  const opsToday = data.by_operation_today ?? [];
  const daily = data.daily_claude ?? [];
  const maxDaily = Math.max(0.01, ...daily.map((d) => d.cost_usd));

  return (
    <section className={`panel claude-usage ${className}`.trim()} aria-label="Claude Code usage">
      <div className="panel__head panel__head--inset">
        <div>
          <div className="panel__title">Claude Code usage</div>
          <div className="panel__sub">
            Anthropic ledger · {data.month}
            {config ? (
              <>
                {" "}
                · apply {config.primary_model}
                {config.fallback_model ? ` → ${config.fallback_model}` : ""}
              </>
            ) : null}
          </div>
        </div>
        <div className="claude-usage__kpis">
          <Kpi label="Today" value={`$${(summary?.claude_today_usd ?? 0).toFixed(2)}`} />
          <Kpi label="Month" value={`$${(summary?.claude_month_usd ?? 0).toFixed(2)}`} />
          <Kpi label="Calls today" value={String(summary?.claude_calls_today ?? 0)} />
          {summary?.cache_hit_rate_percent != null ? (
            <Kpi label="Cache read %" value={`${summary.cache_hit_rate_percent}%`} />
          ) : null}
        </div>
      </div>

      <div className="panel__body panel__body--tight">
        {config && !compact ? (
          <div className="claude-usage__flags">
            <Flag on={config.prompt_slim} label="Slim prompts" />
            <Flag on={config.session_reuse} label="Session reuse" />
            <Flag on={config.gmail_mcp} label="Gmail MCP" />
            {(quota?.quota_blocked_recent ?? 0) > 0 ? (
              <span className="claude-usage__warn">
                {quota?.quota_blocked_recent} quota block(s) in last 7d
              </span>
            ) : null}
          </div>
        ) : null}

        {!compact && daily.length > 0 ? (
          <div className="claude-usage__chart">
            <div className="claude-usage__chart-label">Last 7 days (USD)</div>
            <div className="claude-usage__bars">
              {daily.map((d) => (
                <div key={d.day} className="claude-usage__bar-col" title={`${d.day}: $${d.cost_usd.toFixed(2)}`}>
                  <div
                    className="claude-usage__bar-fill"
                    style={{ height: `${Math.max(4, (d.cost_usd / maxDaily) * 100)}%` }}
                  />
                  <div className="claude-usage__bar-day">{d.day.slice(5)}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {models.length > 0 ? (
          <Breakdown title="By model (month)" rows={models} />
        ) : null}

        {opsToday.length > 0 ? (
          <Breakdown title="By operation (today)" rows={opsToday} />
        ) : null}

        {!compact && (data.recent_events?.length ?? 0) > 0 ? (
          <div className="claude-usage__events">
            <div className="claude-usage__section-title">Recent Claude events</div>
            <div className="claude-usage__table-wrap">
              <table className="claude-usage__table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Op</th>
                    <th>Model</th>
                    <th>Cost</th>
                    <th>Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_events.slice(0, 12).map((ev) => (
                    <tr key={ev.id}>
                      <td>{formatTime(ev.created_at)}</td>
                      <td>{ev.operation}</td>
                      <td>{ev.model}</td>
                      <td>${ev.cost_usd.toFixed(3)}</td>
                      <td className="claude-usage__tok">
                        {ev.input_tokens.toLocaleString()} in
                        {ev.cache_read_tokens > 0
                          ? ` · ${ev.cache_read_tokens.toLocaleString()} cache`
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="claude-usage__kpi">
      <div className="claude-usage__kpi-label">{label}</div>
      <div className="claude-usage__kpi-value">{value}</div>
    </div>
  );
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={on ? "claude-usage__flag claude-usage__flag--on" : "claude-usage__flag"}>
      {label}
    </span>
  );
}

function Breakdown({
  title,
  rows,
}: {
  title: string;
  rows: { key: string; cost_usd: number; calls: number }[];
}) {
  const max = Math.max(0.01, ...rows.map((r) => r.cost_usd));
  return (
    <div className="claude-usage__breakdown">
      <div className="claude-usage__section-title">{title}</div>
      {rows.map((row) => (
        <div key={row.key} className="cost__row">
          <div className="cost__row-top">
            <div className="cost__label">
              {row.key || "(unknown)"}{" "}
              <small>{row.calls} calls</small>
            </div>
            <div className="cost__value">${row.cost_usd.toFixed(2)}</div>
          </div>
          <div className="cost__bar">
            <div
              className="cost__bar-fill"
              style={{ width: `${Math.min(100, (row.cost_usd / max) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(11, 16);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
