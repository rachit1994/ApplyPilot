import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api";

type Props = {
  compact?: boolean;
};

export function ConnectionStatus({ compact = false }: Props) {
  const [online, setOnline] = useState(
    typeof navigator !== "undefined" ? navigator.onLine : true,
  );

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  const { data, isError, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 10_000,
    retry: 1,
    staleTime: 5_000,
  });

  const apiOk = !isError && data?.status === "ok";
  const healthy = online && apiOk;

  const hint = healthy
    ? "Browser online · API reachable"
    : !online
      ? "Browser offline"
      : "API unreachable — is the dashboard server running?";

  const label = healthy ? "Connected" : !online ? "Offline" : "API down";

  const dot = (
    <span
      className={`relative flex h-2 w-2 shrink-0 rounded-full ${
        healthy ? "bg-success" : "bg-danger"
      }`}
    >
      {healthy ? (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-40" />
      ) : null}
    </span>
  );

  if (compact) {
    return (
      <div
        className="flex items-center gap-2 rounded-btn border border-panel-border bg-panel-elevated px-2.5 py-1.5"
        title={hint}
      >
        {dot}
        <span className="text-xs text-ink-3">{label}</span>
      </div>
    );
  }

  return (
    <div className="panel p-3" title={hint}>
      <div className="flex items-center gap-2">
        {dot}
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-ink">{label}</p>
          <p className="truncate text-[10px] text-ink-4">
            {isFetching && !data ? "Checking…" : apiOk ? "Dashboard API" : "No response"}
          </p>
        </div>
      </div>
      {dataUpdatedAt > 0 ? (
        <p className="mt-2 text-[10px] text-ink-5">
          Pinged {new Date(dataUpdatedAt).toLocaleTimeString()}
        </p>
      ) : null}
    </div>
  );
}