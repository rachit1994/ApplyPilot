import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api";

export function ConnectionStatus() {
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

  return (
    <div className="panel p-3" title={hint}>
      <div className="flex items-center gap-2">
        <span
          className={`relative flex h-2 w-2 shrink-0 rounded-full ${
            healthy ? "bg-emerald-400" : "bg-red-400"
          }`}
        >
          {healthy && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-40" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-zinc-200">
            {healthy ? "Connected" : !online ? "Offline" : "API down"}
          </p>
          <p className="truncate text-[10px] text-zinc-500">
            {isFetching && !data ? "Checking…" : apiOk ? "Dashboard API" : "No response"}
          </p>
        </div>
      </div>
      {dataUpdatedAt > 0 && (
        <p className="mt-2 text-[10px] text-zinc-600">
          Pinged {new Date(dataUpdatedAt).toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
