import type { Run } from "../api";

export type ApplyAgentPhase =
  | "idle"
  | "starting"
  | "applying"
  | "waiting"
  | "paused_quota"
  | "stopped"
  | "completed"
  | "failed";

export type WorkerHeartbeatInfo = {
  workerId: number;
  status?: string;
  detail: string;
  at?: string;
};

export type ApplyAgentState = {
  phase: ApplyAgentPhase;
  label: string;
  subtitle: string;
  statusbarClassName: string;
  pulse: boolean;
};

const WORKER_LABELS: Record<string, string> = {
  paused_quota: "Quota pause",
  applying: "Applying",
  idle: "Waiting",
  done: "Done",
  failed: "Failed",
  applied: "Applied",
  starting: "Starting",
  submitted_unverified: "Unverified",
};

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function workerStatusLabel(status?: string): string {
  if (!status) return "Active";
  const key = status.toLowerCase();
  return WORKER_LABELS[key] ?? status.replace(/_/g, " ");
}

export function workerStatusbarClass(status?: string): string {
  const key = (status ?? "").toLowerCase();
  if (key === "paused_quota" || key === "failed") return "statusbar statusbar--warn";
  if (key === "applying" || key === "applied") return "statusbar statusbar--ok";
  if (key === "idle" || key === "starting") return "statusbar statusbar--new";
  return "statusbar";
}

export function deriveApplyAgentState(
  activeRun: Run | null,
  workers: WorkerHeartbeatInfo[],
  starting: boolean,
): ApplyAgentState {
  if (starting) {
    return {
      phase: "starting",
      label: "Starting",
      subtitle: "Launching apply subprocess…",
      statusbarClassName: "statusbar statusbar--new",
      pulse: true,
    };
  }

  if (!activeRun || activeRun.run_type !== "apply") {
    return {
      phase: "idle",
      label: "Idle",
      subtitle: "Visible Chrome by default · start when ready",
      statusbarClassName: "statusbar",
      pulse: false,
    };
  }

  const runStatus = activeRun.status;
  const workerStatuses = workers
    .map((w) => (w.status ?? "").toLowerCase())
    .filter(Boolean);

  if (runStatus === "running") {
    if (workerStatuses.some((s) => s === "paused_quota")) {
      const quotaWorker = workers.find((w) => w.status?.toLowerCase() === "paused_quota");
      return {
        phase: "paused_quota",
        label: "Waiting on quota",
        subtitle: quotaWorker?.detail ?? "Claude quota exhausted · auto-retry scheduled",
        statusbarClassName: "statusbar statusbar--warn",
        pulse: false,
      };
    }
    if (workerStatuses.some((s) => s === "applying" || s === "starting")) {
      const busy = workers.find((w) =>
        ["applying", "starting"].includes(w.status?.toLowerCase() ?? ""),
      );
      return {
        phase: "applying",
        label: "Applying",
        subtitle: busy?.detail ?? `run ${activeRun.id}`,
        statusbarClassName: "statusbar statusbar--ok",
        pulse: true,
      };
    }
    if (workerStatuses.some((s) => s === "idle")) {
      const waiting = workers.find((w) => w.status?.toLowerCase() === "idle");
      return {
        phase: "waiting",
        label: "Waiting",
        subtitle: waiting?.detail ?? "Polling for eligible jobs…",
        statusbarClassName: "statusbar statusbar--new",
        pulse: true,
      };
    }
    return {
      phase: "applying",
      label: "Running",
      subtitle: `run ${activeRun.id} · workers active`,
      statusbarClassName: "statusbar statusbar--ok",
      pulse: true,
    };
  }

  if (runStatus === "stopped") {
    return {
      phase: "stopped",
      label: "Stopped",
      subtitle: activeRun.finished_at
        ? `Stopped ${formatWhen(activeRun.finished_at)}`
        : `run ${activeRun.id}`,
      statusbarClassName: "statusbar statusbar--warn",
      pulse: false,
    };
  }

  if (runStatus === "completed") {
    return {
      phase: "completed",
      label: "Completed",
      subtitle: activeRun.finished_at
        ? `Finished ${formatWhen(activeRun.finished_at)}`
        : `run ${activeRun.id}`,
      statusbarClassName: "statusbar statusbar--ok",
      pulse: false,
    };
  }

  if (runStatus === "failed") {
    return {
      phase: "failed",
      label: "Failed",
      subtitle: activeRun.error_message ?? `run ${activeRun.id} exited with error`,
      statusbarClassName: "statusbar statusbar--warn",
      pulse: false,
    };
  }

  return {
    phase: "idle",
    label: runStatus || "Idle",
    subtitle: `run ${activeRun.id}`,
    statusbarClassName: "statusbar",
    pulse: false,
  };
}

export function summarizeWorkers(workers: WorkerHeartbeatInfo[]): string {
  if (workers.length === 0) return "No worker heartbeats yet";
  const paused = workers.filter((w) => w.status?.toLowerCase() === "paused_quota").length;
  const applying = workers.filter((w) =>
    ["applying", "starting"].includes(w.status?.toLowerCase() ?? ""),
  ).length;
  const waiting = workers.filter((w) => w.status?.toLowerCase() === "idle").length;
  const parts: string[] = [`${workers.length} worker${workers.length === 1 ? "" : "s"}`];
  if (applying) parts.push(`${applying} applying`);
  if (waiting) parts.push(`${waiting} waiting`);
  if (paused) parts.push(`${paused} quota pause`);
  return parts.join(" · ");
}
