import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-chip border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide tabular-nums transition-colors",
  {
    variants: {
      variant: {
        default: "border-panel-border bg-panel-muted text-ink-3",
        secondary: "border-panel-border-strong bg-panel-elevated text-ink-2",
        accent: "border-accent/30 bg-accent-muted text-accent",
        success: "border-success/30 bg-success/10 text-success",
        warning: "border-warning/35 bg-warning/10 text-warning",
        destructive: "border-danger/35 bg-danger/10 text-danger",
        outline: "border-panel-border-strong text-ink-3",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
