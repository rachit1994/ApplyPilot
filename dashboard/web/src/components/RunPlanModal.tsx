import type { ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  cliCommand: string;
  summaryLines: string[];
  children?: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
};

export function RunPlanModal({
  open,
  title,
  cliCommand,
  summaryLines,
  children,
  onCancel,
  onConfirm,
}: Props) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="run-plan-title"
    >
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-card border border-panel-border bg-panel p-5 shadow-xl">
        <h2 id="run-plan-title" className="font-display text-lg text-ink">
          {title}
        </h2>
        <p className="mt-2 text-sm text-ink-3">Review what will run before starting.</p>

        <ul className="mt-4 space-y-1 text-sm text-ink-2">
          {summaryLines.map((line) => (
            <li key={line}>· {line}</li>
          ))}
        </ul>

        <p className="mt-4 text-[10px] font-medium uppercase tracking-wide text-ink-4">CLI equivalent</p>
        <pre className="mt-1 overflow-x-auto rounded border border-panel-border bg-canvas p-2 font-mono text-xs text-ink-2">
          {cliCommand}
        </pre>

        {children ? <div className="mt-4">{children}</div> : null}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-btn border border-panel-border px-4 py-2 text-sm text-ink-2 hover:bg-panel-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90"
          >
            Confirm & start
          </button>
        </div>
      </div>
    </div>
  );
}
