import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  wide?: boolean;
  className?: string;
};

/** Wraps routed page content in finalized.html page/canvas structure. */
export function PageCanvas({ children, wide = false, className }: Props) {
  const canvasClass = wide ? "canvas canvas--wide" : "canvas";
  const extra = className ? ` ${className}` : "";
  return (
    <section className="page page--active" aria-live="polite">
      <div className={`${canvasClass}${extra}`}>{children}</div>
    </section>
  );
}
