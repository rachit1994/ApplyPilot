import { APPLY_QUEUE_ORDER_LABEL, PRIORITY_BOARD_NAMES } from "../utils/sitePriority";
import { Badge } from "./ui/badge";

type Props = {
  applyQueueOrder?: string;
  priorityBoards?: string[];
  compact?: boolean;
};

export function PriorityBoardsBanner({
  applyQueueOrder = APPLY_QUEUE_ORDER_LABEL,
  priorityBoards = [...PRIORITY_BOARD_NAMES],
  compact = false,
}: Props) {
  return (
    <div
      className={
        compact
          ? "flex flex-wrap items-center gap-2 rounded border border-accent/30 bg-accent/5 px-3 py-2 text-xs"
          : "rounded-card border border-accent/30 bg-accent/5 px-4 py-3"
      }
    >
      {!compact ? (
        <p className="text-[10px] font-medium uppercase tracking-wide text-accent">
          Priority boards
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {priorityBoards.map((name) => (
          <Badge key={name} variant="default" className="normal-case">
            {name}
          </Badge>
        ))}
        <span className="text-ink-3">
          {compact ? "first in discover & apply" : "Discover and apply run these first"}
        </span>
      </div>
      {!compact ? (
        <p className="mt-2 font-mono text-[11px] text-ink-4">Apply order: {applyQueueOrder}</p>
      ) : null}
    </div>
  );
}
