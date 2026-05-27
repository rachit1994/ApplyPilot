import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApplications, type Application } from "../api";
import { ApplicationRow } from "./ApplicationRow";

type Props = {
  filterUnverifiedOnly?: boolean;
  onApplicationSelect?: (app: Application) => void;
};

export function ApplicationsPage({
  filterUnverifiedOnly = false,
  onApplicationSelect,
}: Props) {
  const [expandedUrl, setExpandedUrl] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["applications"],
    queryFn: () => fetchApplications({ limit: 200 }),
    refetchInterval: 15_000,
  });

  const applications = useMemo(() => {
    const list = data?.applications ?? [];
    if (!filterUnverifiedOnly) return list;
    return list.filter((a) => a.apply_status === "submitted_unverified");
  }, [data?.applications, filterUnverifiedOnly]);

  return (
    <section className="space-y-4">
      <header>
        <h2 className="font-display text-xl text-ink">Applications</h2>
        <p className="mt-1 text-sm text-ink-3">
          {filterUnverifiedOnly
            ? "Ghost applies need verification — confirm or retry."
            : "Submitted applications with form snapshots and apply logs."}
        </p>
      </header>

      {isLoading ? <p className="text-sm text-ink-3">Loading applications…</p> : null}
      {error ? (
        <p className="text-sm text-bad">{error instanceof Error ? error.message : "Error"}</p>
      ) : null}

      {!isLoading && applications.length === 0 ? (
        <p className="rounded-card border border-panel-border bg-panel p-6 text-sm text-ink-3">
          No applications yet. Run apply from this page or the CLI.
        </p>
      ) : null}

      <div className="space-y-2">
        {applications.map((app) => (
          <ApplicationRow
            key={app.url}
            app={app}
            expanded={expandedUrl === app.url}
            onToggle={() =>
              setExpandedUrl((prev) => (prev === app.url ? null : app.url))
            }
            onOpenDrawer={() => onApplicationSelect?.(app)}
          />
        ))}
      </div>
    </section>
  );
}
