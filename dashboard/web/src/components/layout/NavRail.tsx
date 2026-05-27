import type { ReactNode } from "react";
import type { DashboardPage } from "../../dashboardNav";

type Props = { activePage: DashboardPage; onNavigate: (page: DashboardPage) => void };

const HOME: { id: DashboardPage; label: string; icon: ReactNode } = {
  id: "home",
  label: "Home",
  icon: (
    <Ico>
      <path d="M3 9.5 9 4l6 5.5V16H6v-5H3z" />
    </Ico>
  ),
};

const JOBS: { id: DashboardPage; label: string; icon: ReactNode } = {
  id: "jobs",
  label: "Jobs",
  icon: (
    <Ico>
      <path d="M3 4h12v2H3zM3 8h12v2H3zM3 12h8v2H3z" />
    </Ico>
  ),
};

const APPLY: { id: DashboardPage; label: string; icon: ReactNode } = {
  id: "apply",
  label: "Apply",
  icon: (
    <Ico>
      <path d="M4 14 14 4M8 4h6v6M4 5h4M4 9h2M4 13h1" />
    </Ico>
  ),
};

const APPLICATIONS: { id: DashboardPage; label: string; icon: ReactNode } = {
  id: "applications",
  label: "Apps",
  icon: (
    <Ico>
      <path d="M4 4h10v12H4zM6 7h6M6 10h4" />
    </Ico>
  ),
};

export function NavRail({ activePage, onNavigate }: Props) {
  return (
    <nav
      className="sticky top-0 flex h-screen w-14 shrink-0 flex-col border-r border-panel-border bg-canvas-elevated"
      aria-label="Main navigation"
    >
      <div className="flex h-full flex-col items-center gap-1 py-3.5">
        <div
          className="mb-3.5 grid h-8 w-8 place-items-center rounded-lg border border-panel-border bg-panel text-base font-semibold text-accent"
          aria-hidden
        >
          a
        </div>

        <NavBtn {...HOME} active={activePage === "home"} onClick={() => onNavigate("home")} />
        <NavBtn {...JOBS} active={activePage === "jobs"} onClick={() => onNavigate("jobs")} />
        <NavBtn {...APPLY} active={activePage === "apply"} onClick={() => onNavigate("apply")} />
        <NavBtn
          {...APPLICATIONS}
          active={activePage === "applications"}
          onClick={() => onNavigate("applications")}
        />
      </div>
    </nav>
  );
}

function NavBtn({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`relative flex h-10 w-10 flex-col items-center justify-center gap-0.5 rounded-lg text-ink-4 transition-colors hover:bg-panel-elevated hover:text-ink-2 ${
        active ? "bg-panel-elevated text-ink" : ""
      }`}
    >
      {active ? (
        <span
          className="absolute -left-2 top-1.5 bottom-1.5 w-0.5 rounded-r bg-accent"
          aria-hidden
        />
      ) : null}
      <span className="grid place-items-center">{icon}</span>
      <span className="text-[8px] uppercase tracking-wide opacity-85">{label}</span>
    </button>
  );
}

function Ico({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className="h-[18px] w-[18px]"
      aria-hidden
    >
      {children}
    </svg>
  );
}
