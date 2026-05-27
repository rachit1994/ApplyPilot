import { ConnectionStatus } from "../ConnectionStatus";
import { Button } from "../ui/button";

export type HeaderMetrics = {
  applied: number | string;
  queue: number | string;
  spend: number | string;
  unverified?: number | string;
  workers?: number | string;
  appliesCap?: string;
};

type Props = {
  metrics: HeaderMetrics;
  title?: string;
  subtitle?: string;
  activeRunId?: string | null;
  activeRunLabel?: string | null;
  onStopRun?: () => void;
  stopping?: boolean;
};

export function HeaderStrip({
  metrics,
  title,
  subtitle,
  activeRunId,
  activeRunLabel,
  onStopRun,
  stopping,
}: Props) {
  return (
    <header className="shrink-0 border-b border-panel-border bg-canvas-elevated/95 px-5 py-3 backdrop-blur-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-lg font-medium tracking-tight text-balance text-ink">
            {title ?? "ApplyPilot"}
          </h1>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>
          ) : (
            <p className="mt-0.5 text-[10px] text-ink-4">Local · ~/.applypilot</p>
          )}
          {activeRunId ? (
            <p className="mt-1 font-mono text-[10px] text-accent">
              Run {activeRunId.slice(0, 8)}…
              {activeRunLabel ? ` · ${activeRunLabel}` : ""}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-5">
          <Metric label="Applied" value={metrics.applied} accent />
          {metrics.unverified != null && Number(metrics.unverified) > 0 ? (
            <Metric label="Unverified" value={metrics.unverified} warn />
          ) : null}
          <Metric label="Queue" value={metrics.queue} />
          <Metric label="Spend" value={metrics.spend} prefix="$" />
          {metrics.workers != null ? (
            <Metric label="Workers" value={metrics.workers} />
          ) : null}
          {onStopRun ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={!activeRunId || stopping}
              onClick={onStopRun}
            >
              {stopping ? "Stopping…" : "Stop run"}
            </Button>
          ) : null}
          <ConnectionStatus compact />
        </div>
      </div>
    </header>
  );
}

function Metric({
  label,
  value,
  prefix,
  accent,
  warn,
}: {
  label: string;
  value: number | string;
  prefix?: string;
  accent?: boolean;
  warn?: boolean;
}) {
  const display =
    typeof value === "number"
      ? value.toLocaleString()
      : value === "" || value == null
        ? "—"
        : String(value);

  return (
    <div className="text-right">
      <p className="text-[10px] font-medium uppercase tracking-wide text-ink-4">{label}</p>
      <p
        className={`font-mono text-xl font-semibold tabular-nums ${
          warn ? "text-warn" : accent ? "text-accent" : "text-ink"
        }`}
      >
        {prefix && display !== "—" ? prefix : null}
        {display}
      </p>
    </div>
  );
}
