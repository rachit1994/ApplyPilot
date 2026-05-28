import { pageGreeting, pageSubtitle, pageTitle, type DashboardPage } from "../../dashboardNav";
import type { Run } from "../../api";

type Props = {
  page: DashboardPage;
  subtitle?: string;
  activeRun?: Run | null;
  onStopRun?: () => void;
};

export function HeaderStrip({ page, subtitle, activeRun, onStopRun }: Props) {
  const running = activeRun?.status === "running";
  const sub = subtitle ?? pageSubtitle(page);
  const heading = page === "home" ? pageGreeting() : pageTitle(page);

  return (
    <header className="workspace__head">
      <div className="head__title">
        <h1 className="head__greeting" data-pretext>
          {heading}
        </h1>
        <p className="head__sub">{sub}</p>
      </div>

      <div className="head__right">
        <div className="server-pill" title="ApplyPilot local agent">
          <span className="server-pill__status">
            <span className={`dot ${running ? "dot--live" : ""}`} />
            {running ? "Agent running" : "Agent idle"}
          </span>
          <button
            type="button"
            className="server-pill__btn server-pill__btn--stop"
            title="Stop run"
            disabled={!running}
            onClick={() => onStopRun?.()}
          >
            <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden>
              <rect x="4" y="4" width="6" height="6" rx="1" />
            </svg>
            Stop
          </button>
        </div>

        <button className="head__icon" type="button" title="Notifications">
          <span className="head__icon-dot" />
          <svg
            width="17"
            height="17"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M6 8a4 4 0 018 0c0 5 1.5 6 1.5 6h-11S6 13 6 8z" />
            <path d="M8.5 16a1.5 1.5 0 003 0" />
          </svg>
        </button>

        <div className="head__avatar" title="Local profile">
          RS
        </div>
      </div>
    </header>
  );
}
