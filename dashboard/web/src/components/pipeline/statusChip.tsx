import { cn } from "../../lib/utils";
import { Badge, type BadgeProps } from "../ui/badge";

export type StatusChipVariant =
  | "ready"
  | "running"
  | "verified"
  | "needs-check"
  | "failed";

export interface StatusChipProps {
  variant: StatusChipVariant;
  label?: string;
  className?: string;
}

const DEFAULT_LABELS: Record<StatusChipVariant, string> = {
  ready: "Ready",
  running: "Running",
  verified: "Verified",
  "needs-check": "Needs check",
  failed: "Failed",
};

const VARIANT_MAP: Record<StatusChipVariant, BadgeProps["variant"]> = {
  ready: "secondary",
  running: "accent",
  verified: "success",
  "needs-check": "warning",
  failed: "destructive",
};

export function StatusChip({ variant, label, className = "" }: StatusChipProps) {
  const text = label ?? DEFAULT_LABELS[variant];
  const runningDot = variant === "running";

  return (
    <Badge variant={VARIANT_MAP[variant]} className={cn("font-mono", className)}>
      {runningDot ? (
        <span
          className="size-1.5 shrink-0 rounded-full bg-accent now-live-dot"
          aria-hidden
        />
      ) : null}
      {text}
    </Badge>
  );
}
