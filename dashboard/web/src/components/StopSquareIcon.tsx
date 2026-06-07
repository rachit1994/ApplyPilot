type Props = {
  className?: string;
};

/** Filled stop square — visible at small sizes (stroke-only rects disappear at 11px). */
export function StopSquareIcon({ className }: Props) {
  return (
    <svg viewBox="0 0 14 14" className={className} aria-hidden>
      <rect x="3" y="3" width="8" height="8" rx="1.5" fill="currentColor" />
    </svg>
  );
}
