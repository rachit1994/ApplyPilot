import { pageGreeting, pageSubtitle, pageTitle, type DashboardPage } from "../../dashboardNav";
import type { Run } from "../../api";
import { StopSquareIcon } from "../StopSquareIcon";

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
            <StopSquareIcon />
            Stop
          </button>
        </div>

        <div className="head__avatar" title="Local profile">
          RS
        </div>
      </div>
    </header>
  );
}
