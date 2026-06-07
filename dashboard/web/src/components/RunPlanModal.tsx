import type { ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  subtitle?: string;
  cliCommand: string;
  summaryLines: string[];
  children?: ReactNode;
  confirmDisabled?: boolean;
  confirmLabel?: string;
  wide?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function RunPlanModal({
  open,
  title,
  subtitle = "Review what will run before starting.",
  cliCommand,
  summaryLines,
  children,
  confirmDisabled,
  confirmLabel = "Confirm & start",
  wide,
  onCancel,
  onConfirm,
}: Props) {
  if (!open) return null;

  return (
    <div
      className="run-plan-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="run-plan-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        className={
          wide
            ? "run-plan-modal__sheet run-plan-modal__sheet--wide"
            : "run-plan-modal__sheet run-plan-modal__sheet--default"
        }
        onClick={(e) => e.stopPropagation()}
      >
        <header className="panel__head panel__head--inset run-plan-modal__head">
          <div>
            <h2 id="run-plan-title" className="panel__title">
              {title}
            </h2>
            <p className="panel__sub">{subtitle}</p>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="Close"
            onClick={onCancel}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" aria-hidden>
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="run-plan-modal__body">
          {summaryLines.length > 0 ? (
            <div className="run-plan-modal__summary">
              <ul className="run-plan-modal__summary-list">
                {summaryLines.map((line) => (
                  <li key={line} className="run-plan-modal__summary-item">
                    {line}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {children ? <div className="run-plan-modal__sections">{children}</div> : null}

          <div className="run-plan-modal__cli-block">
            <div className="set-section-title">CLI equivalent</div>
            <pre className="run-plan-modal__cli">{cliCommand}</pre>
          </div>
        </div>

        <footer className="run-plan-modal__foot">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--accent btn--lg"
            onClick={onConfirm}
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  );
}
