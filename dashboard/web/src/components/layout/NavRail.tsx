import type { ReactNode } from "react";
import type { DashboardPage } from "../../dashboardNav";

type BadgeMap = {
  jobs?: number;
  apps?: number;
  outreach?: number;
};

type Props = {
  activePage: DashboardPage;
  onNavigate: (page: DashboardPage) => void;
  badges?: BadgeMap;
};

export function NavRail({ activePage, onNavigate, badges }: Props) {
  return (
    <nav className="rail" aria-label="Primary">
      <div className="rail__logo" aria-hidden>
        a
      </div>

      <NavBtn
        label="Today"
        active={activePage === "home"}
        onClick={() => onNavigate("home")}
        icon={
          <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M4 10.5 11 4l7 6.5V18H5v-6" />
          </svg>
        }
      />

      <NavBtn
        label="Jobs"
        active={activePage === "jobs"}
        onClick={() => onNavigate("jobs")}
        badge={badges?.jobs}
        icon={
          <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <rect x="3.5" y="6" width="15" height="11" rx="2" />
            <path d="M8 6V4.5a1 1 0 011-1h4a1 1 0 011 1V6" />
            <path d="M3.5 11h15" />
          </svg>
        }
      />

      <NavBtn
        label="Apps"
        active={activePage === "applications" || activePage === "apply"}
        onClick={() => onNavigate("applications")}
        badge={badges?.apps}
        badgeWarn
        icon={
          <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m3 11 4 4 12-12" />
          </svg>
        }
      />

      <NavBtn
        label="Outreach"
        active={activePage === "outreach"}
        onClick={() => onNavigate("outreach")}
        badge={badges?.outreach}
        icon={
          <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m20 2-9 9" />
            <path d="M20 2 13 20l-2-9-9-2 18-7z" />
          </svg>
        }
      />

      <NavBtn
        label="Pipeline"
        active={activePage === "pipeline"}
        onClick={() => onNavigate("pipeline")}
        icon={
          <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M3 18V11M8 18V7M13 18v-9M18 18V4" />
          </svg>
        }
      />

      <div className="rail__spacer" />

      <NavBtn
        label="Settings"
        active={activePage === "settings"}
        onClick={() => onNavigate("settings")}
        icon={
          <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <circle cx="11" cy="11" r="3" />
            <path d="M11 2v2.5M11 17.5V20M2 11h2.5M17.5 11H20M4.5 4.5l1.7 1.7M15.8 15.8l1.7 1.7M4.5 17.5l1.7-1.7M15.8 6.2l1.7-1.7" />
          </svg>
        }
      />
    </nav>
  );
}

function NavBtn({
  label,
  icon,
  active,
  onClick,
  badge,
  badgeWarn,
}: {
  label: string;
  icon: ReactNode;
  active: boolean;
  onClick: () => void;
  badge?: number;
  badgeWarn?: boolean;
}) {
  const showBadge = badge != null && badge > 0;
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={active ? "rail__btn rail__btn--active" : "rail__btn"}
    >
      {showBadge ? (
        <span className={badgeWarn ? "rail__badge rail__badge--warn" : "rail__badge"}>
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
      {icon}
      <span className="rail__label">{label}</span>
    </button>
  );
}
