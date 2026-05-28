import type { ReactNode } from "react";
import type { Application, Job, Run } from "../../api";
import type { DashboardPage } from "../../dashboardNav";
import { NavRail } from "./NavRail";
import { HeaderStrip } from "./HeaderStrip";
import { RightDrawer } from "./RightDrawer";

type Props = {
  page: DashboardPage;
  onPageChange: (page: DashboardPage) => void;
  headerSubtitle?: string;
  selectedJob: Job | null;
  selectedApplication: Application | null;
  onCloseDrawer: () => void;
  activeRun: Run | null;
  navBadges?: { jobs?: number; apps?: number; outreach?: number };
  onStopRun?: () => void;
  children: ReactNode;
};

const INLINE_DETAIL_PAGES: DashboardPage[] = ["jobs", "applications", "outreach"];

export function DashboardLayout({
  page,
  onPageChange,
  headerSubtitle,
  selectedJob,
  selectedApplication,
  onCloseDrawer,
  activeRun,
  navBadges,
  onStopRun,
  children,
}: Props) {
  const useDrawer = !INLINE_DETAIL_PAGES.includes(page);

  return (
    <div className="app">
      <NavRail activePage={page} onNavigate={onPageChange} badges={navBadges} />

      <div className="workspace">
        <HeaderStrip
          page={page}
          subtitle={headerSubtitle}
          activeRun={activeRun}
          onStopRun={onStopRun}
        />

        <main className="workspace__main">{children}</main>
      </div>

      {useDrawer ? (
        <RightDrawer job={selectedJob} application={selectedApplication} onClose={onCloseDrawer} />
      ) : null}
    </div>
  );
}
