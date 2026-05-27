import type { StatusChipVariant } from "./statusChip";
import { StatusChip } from "./statusChip";

export interface WorkerChipProps {
  /** Worker id shown in header, e.g. W0 */
  id?: string;
  title: string;
  ats: string;
  subStep: string;
  /** Human-readable elapsed, e.g. 00:23 */
  elapsed: string;
  /** Cost so far, e.g. $0.034 */
  costSoFar: string;
  /** Pulse + accent border when true */
  active?: boolean;
  /** Amber pause styling inside the chip */
  paused?: boolean;
  selected?: boolean;
  statusVariant?: StatusChipVariant;
  onClick?: () => void;
  className?: string;
}

export function WorkerChip({
  id,
  title,
  ats,
  subStep,
  elapsed,
  costSoFar,
  active = false,
  paused = false,
  selected = false,
  statusVariant,
  onClick,
  className = "",
}: WorkerChipProps) {
  const interactive = Boolean(onClick);
  const chipStatus: StatusChipVariant =
    statusVariant ?? (paused ? "needs-check" : active ? "running" : "ready");

  const rootClass = [
    "flex flex-col gap-2.5 rounded-xl border p-3.5 text-left transition-colors",
    "border-panel-border bg-panel",
    active && !paused ? "worker-chip-active border-accent/30 shadow-[0_0_30px_-16px] shadow-accent/25" : "",
    paused
      ? "border-warning/35 bg-gradient-to-b from-warning/[0.06] to-transparent"
      : "",
    selected ? "ring-1 ring-accent/40" : "",
    interactive ? "cursor-pointer hover:border-panel-hover" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const Root = interactive ? "button" : "article";

  return (
    <Root
      type={interactive ? "button" : undefined}
      className={rootClass}
      onClick={onClick}
      aria-pressed={interactive ? selected : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="rounded border border-panel-border bg-canvas-elevated px-1.5 py-0.5 font-mono text-[11px] tracking-wide text-text-muted">
          {id ? `${id} · ` : ""}
          {ats.toUpperCase()}
        </span>
        <span className="font-mono text-[11px] text-text-muted tabular-nums">
          {paused ? (
            <>
              paused <b className="font-medium text-text-primary">{elapsed}</b>
            </>
          ) : (
            <>
              elapsed <b className="font-medium text-text-primary">{elapsed}</b>
            </>
          )}
        </span>
      </div>

      <div>
        <div className="text-sm font-medium leading-snug text-text-primary">{title}</div>
        <div className="mt-0.5 truncate font-mono text-[11px] text-text-muted">
          <span className="text-success">{ats}</span>
        </div>
      </div>

      <div className="rounded-lg border border-panel-border bg-canvas-elevated/60 px-2.5 py-2 text-xs leading-relaxed text-text-secondary">
        <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-text-muted">
          Sub-step
        </span>
        {subStep}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-panel-border pt-2">
        <StatusChip variant={chipStatus} />
        <span className="font-mono text-[10.5px] text-text-muted tabular-nums">
          cost <b className="font-medium text-text-primary">{costSoFar}</b>
        </span>
      </div>
    </Root>
  );
}
