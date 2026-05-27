import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchActiveRun,
  fetchStats,
  stopRun,
  type Application,
  type Job,
} from "./api";
import { DashboardLayout } from "./components/layout/DashboardLayout";
import type { HeaderMetrics } from "./components/layout/HeaderStrip";
import { HomePage } from "./components/HomePage";
import { JobsExplorerPage } from "./components/JobsExplorerPage";
import { ApplyPage } from "./components/ApplyPage";
import { AppliedApplicationsPage } from "./components/AppliedApplicationsPage";
import type { DashboardPage } from "./dashboardNav";
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

function readPageFromUrl(): DashboardPage {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  if (tab === "applications") return "applications";
  if (tab === "apply") return "apply";
  if (tab === "jobs") return "jobs";
  // Legacy: ?page=jobs before pagination reused `page`
  const legacyPage = params.get("page");
  if (legacyPage === "applications") return "applications";
  if (legacyPage === "apply") return "apply";
  if (legacyPage === "jobs") return "jobs";
  // Deep links with filters but no tab (e.g. ?stage=needs_check&page=2)
  if (JOBS_FILTER_KEYS.some((key) => params.has(key))) return "jobs";
  if (legacyPage && /^\d+$/.test(legacyPage)) return "jobs";
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
  const queryClient = useQueryClient();
  const [page, setPage] = useState<DashboardPage>(readPageFromUrl);
  const [jobsSearch, setJobsSearch] = useState<URLSearchParams>(jobsParamsFromUrl);
  const [applicationsFilter, setApplicationsFilter] = useState<string | null>(
    applicationsFilterFromUrl,
  );
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [selectedApplication, setSelectedApplication] = useState<Application | null>(null);
  const [stopping, setStopping] = useState(false);

  const syncUrl = useCallback(
    (nextPage: DashboardPage, jobsParams: URLSearchParams, appFilter: string | null) => {
      const url = new URL(window.location.href);
      const jobsFilterKeys = [...JOBS_FILTER_KEYS, "page"] as const;
      for (const key of jobsFilterKeys) {
        url.searchParams.delete(key);
      }
      for (const key of APPLICATIONS_FILTER_KEYS) {
        url.searchParams.delete(key);
      }
      url.searchParams.delete("page");

      if (nextPage === "jobs") {
        url.searchParams.set("tab", "jobs");
        jobsParams.forEach((value, key) => {
          if (value) url.searchParams.set(key, value);
        });
      } else if (nextPage === "apply") {
        url.searchParams.set("tab", "apply");
      } else if (nextPage === "applications") {
        url.searchParams.set("tab", "applications");
        if (appFilter) url.searchParams.set("filter", appFilter);
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
    syncUrl(page, jobsSearch, applicationsFilter);
  }, [page, jobsSearch, applicationsFilter, syncUrl]);

  useEffect(() => {
    const onPopState = () => {
      setPage(readPageFromUrl());
      setJobsSearch(jobsParamsFromUrl());
      setApplicationsFilter(applicationsFilterFromUrl());
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const { data: activeRun } = useQuery({
    queryKey: ["runs", "active"],
    queryFn: fetchActiveRun,
    refetchInterval: 5000,
  });

  const headerMetrics: HeaderMetrics = useMemo(() => {
    const extra = stats?.extra ?? {};
    const spendRaw = extra.llm_cost_today ?? extra.cost_today ?? extra.spend_today;
    const spend =
      typeof spendRaw === "number"
        ? spendRaw.toFixed(2)
        : typeof spendRaw === "string"
          ? spendRaw
          : "—";

    return {
      applied: stats?.applied ?? "—",
      queue: stats?.ready_to_apply ?? stats?.pipeline?.pending_apply ?? "—",
      spend,
      unverified: stats?.pipeline?.submitted_unverified ?? 0,
      workers: extra.active_workers ?? "—",
    };
  }, [stats]);

  const handlePageChange = (next: DashboardPage) => {
    setPage(next);
    setSelectedJob(null);
    setSelectedApplication(null);
  };

  const handleOpenJobs = useCallback(
    (params?: Record<string, string>) => {
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
    },
    [],
  );

  const handleOpenApplications = useCallback((params?: Record<string, string>) => {
    setApplicationsFilter(params?.filter ?? null);
    setPage("applications");
    setSelectedJob(null);
    setSelectedApplication(null);
  }, []);

  const handleApplicationsFilterChange = useCallback((filter: ApplyStatusFilter) => {
    setApplicationsFilter(applyFilterToUrlParam(filter));
  }, []);

  const handleStopRun = useCallback(async () => {
    if (!activeRun?.id || activeRun.status !== "running") return;
    setStopping(true);
    try {
      await stopRun(activeRun.id);
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
    } finally {
      setStopping(false);
    }
  }, [activeRun?.id, activeRun?.status, queryClient]);

  let content;
  if (page === "jobs") {
    content = (
      <JobsExplorerPage
        searchParams={jobsSearch}
        onSearchParamsChange={setJobsSearch}
        onJobSelect={setSelectedJob}
      />
    );
  } else if (page === "apply") {
    content = (
      <ApplyPage
        unverifiedCount={stats?.pipeline?.submitted_unverified ?? 0}
        onOpenApplications={handleOpenApplications}
      />
    );
  } else if (page === "applications") {
    content = (
      <AppliedApplicationsPage
        initialFilter={applicationsFilter}
        onFilterChange={handleApplicationsFilterChange}
      />
    );
  } else {
    content = <HomePage onOpenJobs={handleOpenJobs} onOpenApplications={handleOpenApplications} />;
  }

  return (
    <DashboardLayout
      page={page}
      onPageChange={handlePageChange}
      headerMetrics={headerMetrics}
      selectedJob={selectedJob}
      selectedApplication={selectedApplication}
      onCloseDrawer={() => {
        setSelectedJob(null);
        setSelectedApplication(null);
      }}
      activeRun={activeRun ?? null}
      onStopRun={handleStopRun}
      stopping={stopping}
    >
      {content}
    </DashboardLayout>
  );
}
