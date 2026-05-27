import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchInboxQueue,
  postInboxRun,
  postInboxScan,
  type InboxQueueItem,
} from "../api";
import { ConnectionStatus } from "./ConnectionStatus";

export function InboxPage() {
  const queryClient = useQueryClient();
  const [limit, setLimit] = useState(50);
  const [message, setMessage] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["inbox", "queue", limit],
    queryFn: () => fetchInboxQueue(limit),
    refetchInterval: 30_000,
  });

  const scanMut = useMutation({
    mutationFn: () => postInboxScan(limit),
    onSuccess: (res) => {
      setMessage(`Scan complete: ${JSON.stringify(res).slice(0, 120)}…`);
      void refetch();
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "Scan failed"),
  });

  const runMut = useMutation({
    mutationFn: () =>
      postInboxRun({ action: "pipeline", limit, subprocess: true, dry_run: false }),
    onSuccess: (res) => {
      const run = (res as { run?: { id?: string } }).run;
      setMessage(run?.id ? `Inbox run started (${run.id.slice(0, 8)}…)` : "Inbox pipeline started");
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "Run failed"),
  });

  const stats = data?.stats ?? {};
  const queue = data?.queue ?? [];

  return (
    <div className="space-y-6 pb-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-xl text-ink">Inbox</h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-3">
            LinkedIn <span className="font-mono text-ink-2">Other</span> tab — ranked threads where
            recruiters invited you to apply. Scan, review, then run the pipeline.
          </p>
        </div>
        <ConnectionStatus />
      </header>

      {message ? (
        <p className="rounded-card border border-panel-border bg-panel px-4 py-2 text-sm text-ink-2">
          {message}
        </p>
      ) : null}

      <section className="panel flex flex-wrap items-center gap-3 p-4">
        <button
          type="button"
          disabled={scanMut.isPending}
          onClick={() => scanMut.mutate()}
          className="rounded-btn border border-panel-border px-4 py-2 text-sm hover:bg-panel-elevated disabled:opacity-40"
        >
          {scanMut.isPending ? "Scanning…" : "Scan Other tab"}
        </button>
        <button
          type="button"
          disabled={runMut.isPending}
          onClick={() => runMut.mutate()}
          className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90 disabled:opacity-40"
        >
          {runMut.isPending ? "Starting…" : "Run pipeline"}
        </button>
        <label className="ml-auto flex items-center gap-2 text-xs text-ink-3">
          Limit
          <input
            type="number"
            min={1}
            max={200}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="w-16 rounded border border-panel-border bg-canvas px-2 py-1 text-sm"
          />
        </label>
      </section>

      <section className="flex flex-wrap gap-4 text-xs text-ink-3">
        {Object.entries(stats).map(([k, v]) => (
          <span key={k}>
            {k}: <strong className="text-ink">{v}</strong>
          </span>
        ))}
      </section>

      {isLoading ? <p className="text-sm text-ink-3">Loading queue…</p> : null}
      {error ? (
        <p className="text-sm text-bad">
          {error instanceof Error ? error.message : "Failed to load inbox"}
        </p>
      ) : null}

      {!isLoading && queue.length === 0 ? (
        <p className="rounded-card border border-panel-border bg-panel p-6 text-sm text-ink-3">
          No ranked opportunities yet. Run scan after OpenOutreach is up and LinkedIn is logged in.
        </p>
      ) : (
        <ul className="space-y-2">
          {queue.map((item) => (
            <InboxRow key={item.conversation_urn} item={item} />
          ))}
        </ul>
      )}

      <p className="text-xs text-ink-4">
        CLI: <code className="font-mono text-accent">applypilot inbox scan</code> ·{" "}
        <code className="font-mono text-accent">applypilot inbox list</code> ·{" "}
        <code className="font-mono text-accent">applypilot inbox run</code>
      </p>
    </div>
  );
}

function InboxRow({ item }: { item: InboxQueueItem }) {
  const eligible = item.eligible_to_send !== false && !item.skip_reason;
  return (
    <li className="rounded-card border border-panel-border bg-panel px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">
            {item.extracted_title ?? "Role unknown"}
            {item.extracted_company ? (
              <span className="font-normal text-ink-3"> · {item.extracted_company}</span>
            ) : null}
          </p>
          <p className="mt-1 line-clamp-2 text-xs text-ink-3">{item.inbound_preview}</p>
          {item.reasoning ? (
            <p className="mt-2 text-xs text-ink-4">{item.reasoning}</p>
          ) : null}
        </div>
        <div className="text-right">
          <p className="font-mono text-lg font-semibold tabular-nums text-accent">
            {item.fit_score?.toFixed(1) ?? "—"}
          </p>
          <p className="text-[10px] uppercase text-ink-4">fit</p>
          {item.rank != null ? (
            <p className="mt-1 font-mono text-[10px] text-ink-4">#{item.rank}</p>
          ) : null}
        </div>
      </div>
      {item.skip_reason ? (
        <p className="mt-2 text-xs text-warn">Skip: {item.skip_reason}</p>
      ) : eligible ? (
        <p className="mt-2 text-xs text-good">Eligible to send when pipeline runs</p>
      ) : null}
    </li>
  );
}
