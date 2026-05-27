import type { ReactNode } from "react";
import type { Application, Job, Run } from "../../api";
import { pageSubtitle, pageTitle, type DashboardPage } from "../../dashboardNav";
import { NavRail } from "./NavRail";
import { HeaderStrip, type HeaderMetrics } from "./HeaderStrip";
import { RightDrawer } from "./RightDrawer";

type Props = {
  page: DashboardPage;
  onPageChange: (page: DashboardPage) => void;
  headerMetrics: HeaderMetrics;
  selectedJob: Job | null;
  selectedApplication: Application | null;
  onCloseDrawer: () => void;
  activeRun: Run | null;
  onStopRun: () => void;
  stopping?: boolean;
  children: ReactNode;
};

export function DashboardLayout({
  page,
  onPageChange,
  headerMetrics,
  selectedJob,
  selectedApplication,
  onCloseDrawer,
  activeRun,
  onStopRun,
  stopping,
  children,
}: Props) {
  const runLabel =
    activeRun?.status === "running"
      ? `${activeRun.run_type}${activeRun.current_stage ? ` · ${activeRun.current_stage}` : ""}`
      : null;

  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-ink">
      <NavRail activePage={page} onNavigate={onPageChange} />

      <div className="flex min-w-0 flex-1 flex-col">
        <HeaderStrip
          metrics={headerMetrics}
          subtitle={pageSubtitle(page)}
          title={pageTitle(page)}
          activeRunId={activeRun?.status === "running" ? activeRun.id : null}
          activeRunLabel={runLabel}
          onStopRun={onStopRun}
          stopping={stopping}
        />

        <div className="flex min-h-0 flex-1">
          <main className="scroll-thin min-h-0 min-w-0 flex-1 overflow-y-auto p-5">
            {children}
          </main>
          <RightDrawer
            job={selectedJob}
            application={selectedApplication}
            onClose={onCloseDrawer}
          />
        </div>
      </div>
    </div>
  );
}
