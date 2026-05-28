import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchStats,
  stopRun,
  type Application,
  type Job,
} from "./api";
import { DashboardLayout } from "./components/layout/DashboardLayout";
import { HomePage } from "./components/HomePage";
import { JobsExplorerPage } from "./components/JobsExplorerPage";
import { AppliedApplicationsPage } from "./components/AppliedApplicationsPage";
import { OutreachDashboardPage } from "./components/OutreachDashboardPage";
import { PipelineDashboardPage } from "./components/PipelineDashboardPage";
import { SettingsDashboardPage } from "./components/SettingsDashboardPage";
import type { DashboardPage } from "./dashboardNav";
import { isDashboardPage, pageSubtitleWithStats } from "./dashboardNav";
import type { ApplyStatusFilter } from "./utils/applicationAudit";

const JOBS_FILTER_KEYS = [
  "stage",
  "min_score",
  "site",
  "search",
  "sort",
  "apply_status",
  "limit",
] as const;

const APPLICATIONS_FILTER_KEYS = ["filter"] as const;

const PAGE_PATH: Record<DashboardPage, string> = {
  home: "/",
  jobs: "/jobs",
  apply: "/applications",
  applications: "/applications",
  outreach: "/outreach",
  pipeline: "/pipeline",
  settings: "/settings",
};

function pageFromPathname(pathname: string): DashboardPage | null {
  const path = pathname.replace(/\/$/, "") || "/";
  if (path === "/" || path === "/today" || path === "/home") return "home";
  if (path === "/jobs") return "jobs";
  if (path === "/applications" || path === "/apply") return "applications";
  if (path === "/outreach") return "outreach";
  if (path === "/pipeline") return "pipeline";
  if (path === "/settings") return "settings";
  return null;
}

function readPageFromUrl(): DashboardPage {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  if (tab && isDashboardPage(tab)) {
    if (tab === "apply") return "applications";
    return tab;
  }
  const legacyPage = params.get("page");
  if (legacyPage === "applications") return "applications";
  if (legacyPage === "apply") return "applications";
  if (legacyPage === "jobs") return "jobs";
  if (JOBS_FILTER_KEYS.some((key) => params.has(key))) return "jobs";
  if (legacyPage && /^\d+$/.test(legacyPage)) return "jobs";
  const fromPath = pageFromPathname(window.location.pathname);
  if (fromPath) return fromPath;
  return "home";
}

function jobsParamsFromUrl(): URLSearchParams {
  const params = new URLSearchParams(window.location.search);
  const jobs = new URLSearchParams();
  for (const key of [...JOBS_FILTER_KEYS, "page"]) {
    const v = params.get(key);
    if (v) jobs.set(key, v);
  }
  return jobs;
}

function applicationsFilterFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("filter");
}

function applyFilterToUrlParam(filter: ApplyStatusFilter): string | null {
  if (filter === "submitted_unverified") return "unverified";
  if (filter === "all") return null;
  return filter;
}

export default function App() {
  const [page, setPage] = useState<DashboardPage>(readPageFromUrl);
  const [jobsSearch, setJobsSearch] = useState<URLSearchParams>(jobsParamsFromUrl);
  const [applicationsFilter, setApplicationsFilter] = useState<string | null>(
    applicationsFilterFromUrl,
  );
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [selectedApplication, setSelectedApplication] = useState<Application | null>(null);
  const [appsShowApplyControls, setAppsShowApplyControls] = useState(
    () => new URLSearchParams(window.location.search).get("tab") === "apply",
  );

  const syncUrl = useCallback(
    (
      nextPage: DashboardPage,
      jobsParams: URLSearchParams,
      appFilter: string | null,
      applyQueue: boolean,
    ) => {
      const url = new URL(window.location.href);
      const jobsFilterKeys = [...JOBS_FILTER_KEYS, "page"] as const;
      for (const key of jobsFilterKeys) {
        url.searchParams.delete(key);
      }
      for (const key of APPLICATIONS_FILTER_KEYS) {
        url.searchParams.delete(key);
      }
      url.searchParams.delete("page");
      url.pathname = PAGE_PATH[nextPage];

      if (nextPage === "jobs") {
        url.searchParams.set("tab", "jobs");
        jobsParams.forEach((value, key) => {
          if (value) url.searchParams.set(key, value);
        });
      } else if (nextPage === "applications") {
        url.searchParams.set("tab", applyQueue ? "apply" : "applications");
        if (appFilter) url.searchParams.set("filter", appFilter);
      } else if (nextPage === "outreach") {
        url.searchParams.set("tab", "outreach");
      } else if (nextPage === "pipeline") {
        url.searchParams.set("tab", "pipeline");
      } else if (nextPage === "settings") {
        url.searchParams.set("tab", "settings");
      } else {
        url.searchParams.delete("tab");
      }

      const qs = url.searchParams.toString();
      const path = `${url.pathname}${qs ? `?${qs}` : ""}`;
      window.history.replaceState(null, "", path);
    },
    [],
  );

  useEffect(() => {
    syncUrl(page, jobsSearch, applicationsFilter, appsShowApplyControls);
  }, [page, jobsSearch, applicationsFilter, appsShowApplyControls, syncUrl]);

  useEffect(() => {
    const onPopState = () => {
      setPage(readPageFromUrl());
      setJobsSearch(jobsParamsFromUrl());
      setApplicationsFilter(applicationsFilterFromUrl());
      const tab = new URLSearchParams(window.location.search).get("tab");
      setAppsShowApplyControls(tab === "apply");
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
    refetchInterval: 15_000,
  });

  const { data: activeRun } = useQuery({
    queryKey: ["runs", "active"],
    queryFn: fetchActiveRun,
    refetchInterval: 5000,
  });

  const navBadges = useMemo(() => {
    const pipeline = stats?.pipeline;
    const newJobs =
      (pipeline?.scored ?? 0) + (pipeline?.unscored ?? 0) || stats?.scored || undefined;
    return {
      jobs: newJobs,
      apps: stats?.pipeline?.submitted_unverified ?? undefined,
      outreach: stats?.extra?.inbox_queue ?? stats?.extra?.outreach_queue ?? undefined,
    };
  }, [stats]);

  const handlePageChange = (next: DashboardPage) => {
    setPage(next);
    setSelectedJob(null);
    setSelectedApplication(null);
    if (next !== "applications") {
      setAppsShowApplyControls(false);
    }
  };

  const handleOpenJobs = useCallback((params?: Record<string, string>) => {
    const next = new URLSearchParams();
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v) next.set(k, v);
      }
    }
    setJobsSearch(next);
    setPage("jobs");
    setSelectedJob(null);
    setSelectedApplication(null);
  }, []);

  const handleOpenOutreach = useCallback(() => {
    setPage("outreach");
    setSelectedJob(null);
    setSelectedApplication(null);
  }, []);

  const handleOpenApplications = useCallback((params?: Record<string, string>) => {
    setApplicationsFilter(params?.filter ?? null);
    setAppsShowApplyControls(false);
    setPage("applications");
    setSelectedJob(null);
    setSelectedApplication(null);
  }, []);

  const handleApplicationsFilterChange = useCallback((filter: ApplyStatusFilter) => {
    setApplicationsFilter(applyFilterToUrlParam(filter));
  }, []);

  const handleStopRun = useCallback(() => {
    const id = activeRun?.id;
    if (id) void stopRun(id);
  }, [activeRun?.id]);

  const headerSubtitle = useMemo(
    () => pageSubtitleWithStats(page, stats),
    [page, stats],
  );

  let content;
  if (page === "jobs") {
    content = (
      <JobsExplorerPage
        searchParams={jobsSearch}
        onSearchParamsChange={setJobsSearch}
        onJobSelect={setSelectedJob}
      />
    );
  } else if (page === "applications") {
    content = (
      <AppliedApplicationsPage
        initialFilter={applicationsFilter}
        onFilterChange={handleApplicationsFilterChange}
        showApplyControls={appsShowApplyControls}
      />
    );
  } else if (page === "outreach") {
    content = <OutreachDashboardPage />;
  } else if (page === "pipeline") {
    content = <PipelineDashboardPage />;
  } else if (page === "settings") {
    content = <SettingsDashboardPage />;
  } else {
    content = (
      <HomePage
        onOpenJobs={handleOpenJobs}
        onOpenApplications={handleOpenApplications}
        onOpenOutreach={handleOpenOutreach}
      />
    );
  }

  return (
    <DashboardLayout
      page={page}
      onPageChange={handlePageChange}
      headerSubtitle={headerSubtitle}
      selectedJob={selectedJob}
      selectedApplication={selectedApplication}
      onCloseDrawer={() => {
        setSelectedJob(null);
        setSelectedApplication(null);
      }}
      activeRun={activeRun ?? null}
      navBadges={navBadges}
      onStopRun={handleStopRun}
    >
      {content}
    </DashboardLayout>
  );
}
