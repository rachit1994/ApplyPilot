import * as React from "react";
import { cn } from "../../lib/utils";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement>;

export function IconButton({ className, type = "button", ...props }: Props) {
  return (
    <button
      type={type}
      className={cn(
        "inline-grid h-[22px] w-[22px] place-items-center rounded border border-transparent text-ink-4 transition-colors",
        "hover:border-panel-border hover:bg-panel-elevated hover:text-ink-2",
        className,
      )}
      {...props}
    />
  );
}

