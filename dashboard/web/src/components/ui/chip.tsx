import * as React from "react";
import { cn } from "../../lib/utils";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  selected?: boolean;
};

export function Chip({ className, selected, type = "button", ...props }: Props) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center gap-1 rounded-chip border px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-[0.12em] transition-colors",
        selected
          ? "border-[color:var(--acc-line)] bg-[color:var(--acc-bg)] text-accent"
          : "border-panel-border bg-transparent text-ink-3 hover:border-panel-border-strong hover:text-ink-2",
        className,
      )}
      {...props}
    />
  );
}

