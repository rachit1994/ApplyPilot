import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchInboxQueue,
  postInboxRun,
  postInboxScan,
  type InboxQueueItem,
} from "../api";
import { PageCanvas } from "./layout/PageCanvas";
import { ConnectionStatus } from "./ConnectionStatus";

export function OutreachDashboardPage() {
  const queryClient = useQueryClient();
  const [limit, setLimit] = useState(50);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedUrn, setSelectedUrn] = useState<string | null>(null);
  const [tab, setTab] = useState<"drafts" | "sent">("drafts");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["inbox", "queue", limit],
    queryFn: () => fetchInboxQueue(limit),
    refetchInterval: 30_000,
  });

  const scanMut = useMutation({
    mutationFn: () => postInboxScan(limit),
    onSuccess: () => {
      setMessage("Scan complete — queue refreshed.");
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
      setMessage(run?.id ? `Inbox pipeline started (${run.id.slice(0, 8)}…)` : "Pipeline started");
      queryClient.invalidateQueries({ queryKey: ["runs", "active"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "Run failed"),
  });

  const queue = data?.queue ?? [];
  const draftCount = queue.filter((q) => q.eligible_to_send !== false && !q.skip_reason).length;

  const selected = useMemo(
    () => queue.find((q) => q.conversation_urn === selectedUrn) ?? queue[0] ?? null,
    [queue, selectedUrn],
  );

  return (
    <PageCanvas wide>
      <div className="outreach-grid">
        <div className="outreach__list">
          <div className="outreach__hd">
            <div style={{ fontFamily: "var(--display)", fontSize: 15, fontWeight: 600, color: "var(--ink)", letterSpacing: "-0.015em" }}>
              LinkedIn outreach
            </div>
            <button
              type="button"
              className="icon-btn"
              title="Run pipeline"
              disabled={runMut.isPending}
              onClick={() => runMut.mutate()}
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" aria-hidden>
                <path d="m14 2-6 6M14 2 9 14l-1-6-6-1L14 2z" />
              </svg>
            </button>
          </div>

          <div className="outreach__tabs" role="tablist">
            <button
              type="button"
              role="tab"
              className={tab === "drafts" ? "chip chip--on" : "chip"}
              onClick={() => setTab("drafts")}
            >
              Drafts
              {draftCount > 0 ? <span className="chip__count">{draftCount}</span> : null}
            </button>
            <button
              type="button"
              role="tab"
              className={tab === "sent" ? "chip chip--on" : "chip"}
              onClick={() => setTab("sent")}
            >
              Sent
            </button>
          </div>

          <div className="outreach__toolbar" style={{ padding: "8px 12px", display: "flex", gap: 8, flexWrap: "wrap", borderBottom: "1px solid var(--hair)" }}>
            <button
              type="button"
              className="btn btn--sm"
              disabled={scanMut.isPending}
              onClick={() => scanMut.mutate()}
            >
              {scanMut.isPending ? "Scanning…" : "Scan Other tab"}
            </button>
            <ConnectionStatus />
            <label className="panel__sub" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
              Limit
              <input
                type="number"
                min={1}
                max={200}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="jobs__search"
                style={{ width: 56 }}
              />
            </label>
          </div>

          {message ? (
            <p className="panel__sub" style={{ padding: "8px 14px", margin: 0 }}>
              {message}
            </p>
          ) : null}

          <div className="outreach__scroll">
            {isLoading ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                Loading queue…
              </p>
            ) : null}
            {error ? (
              <p style={{ padding: 16, color: "var(--bad)", fontSize: 13 }}>
                {error instanceof Error ? error.message : "Failed to load inbox"}
              </p>
            ) : null}
            {!isLoading && queue.length === 0 ? (
              <p className="panel__sub" style={{ padding: 16 }}>
                No ranked opportunities yet. Scan the LinkedIn Other tab after OpenOutreach is running.
              </p>
            ) : (
              queue.map((item) => (
                <ContactRow
                  key={item.conversation_urn}
                  item={item}
                  selected={selected?.conversation_urn === item.conversation_urn}
                  onSelect={() => setSelectedUrn(item.conversation_urn)}
                />
              ))
            )}
          </div>
        </div>

        <DraftPane item={selected} tab={tab} />
      </div>
    </PageCanvas>
  );
}

function ContactRow({
  item,
  selected,
  onSelect,
}: {
  item: InboxQueueItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const name = item.participant_public_id || "Recruiter";
  const role = [item.extracted_title, item.extracted_company].filter(Boolean).join(" · ");
  const preview = item.inbound_preview?.slice(0, 160) ?? "";

  return (
    <button
      type="button"
      className={selected ? "contact-row contact-row--selected" : "contact-row"}
      onClick={onSelect}
    >
      <div className="contact-row__top">
        <span className="contact-row__name">
          <span className="dot dot--acc" />
          {name}
        </span>
        <span className="contact-row__time">
          {item.skip_reason ? "Skip" : item.eligible_to_send !== false ? "Draft" : "Review"}
        </span>
      </div>
      <div className="contact-row__role">{role || "Role unknown"}</div>
      <div className="contact-row__preview">{preview}</div>
      {item.fit_score != null ? (
        <div className="contact-row__preview" style={{ marginTop: 4, color: "var(--acc)" }}>
          Fit {item.fit_score.toFixed(1)}
          {item.rank != null ? ` · #${item.rank}` : ""}
        </div>
      ) : null}
    </button>
  );
}

function DraftPane({ item, tab }: { item: InboxQueueItem | null; tab: "drafts" | "sent" }) {
  if (!item) {
    return (
      <div className="draft">
        <div className="draft__hd">
          <p className="panel__sub">Select a thread to preview the ranked outreach draft.</p>
        </div>
      </div>
    );
  }

  const initials = (item.participant_public_id ?? "?").slice(0, 2).toUpperCase();
  const title = item.extracted_title ?? "Opportunity";
  const company = item.extracted_company ?? "";

  const draftBody =
    tab === "sent"
      ? "Sent messages are tracked via OpenOutreach; select Drafts for pending replies."
      : item.reasoning
        ? `${item.reasoning}\n\n---\nInbound: ${item.inbound_preview}`
        : `Reply draft for: ${title}${company ? ` at ${company}` : ""}.\n\nRun the inbox pipeline to generate and send via LinkedIn Other tab.`;

  return (
    <div className="draft">
      <div className="draft__hd">
        <div className="draft__contact">
          <div className="draft__avatar">{initials}</div>
          <div>
            <div className="draft__name">{item.participant_public_id ?? "Recruiter"}</div>
            <div className="draft__name-sub">
              {title}
              {company ? ` · ${company}` : ""}
            </div>
          </div>
        </div>
        <div className="draft__job" data-pretext>
          Re: {title}
        </div>
        <div className="draft__tags">
          {item.fit_score != null ? (
            <span className="tag" style={{ background: "var(--acc-dim)", color: "var(--acc)", fontWeight: 600 }}>
              Fit {item.fit_score.toFixed(1)}
            </span>
          ) : null}
          {item.skip_reason ? (
            <span className="tag" style={{ background: "var(--warn-dim)", color: "var(--warn)" }}>
              {item.skip_reason}
            </span>
          ) : item.eligible_to_send !== false ? (
            <span className="tag">Eligible to send</span>
          ) : null}
        </div>
      </div>

      <div className="draft__body">
        <textarea className="draft__editor" spellCheck={false} readOnly value={draftBody} />
        <div className="draft__hint">
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" aria-hidden>
            <circle cx="7" cy="7" r="5.5" />
            <path d="M7 4v3.5" />
            <circle cx="7" cy="10" r="0.5" fill="currentColor" />
          </svg>
          <div>
            LinkedIn Other-tab scan only. Use <code>applypilot inbox run</code> to send ranked replies with
            OpenOutreach.
          </div>
        </div>
      </div>

      <div className="draft__actions">
        <button type="button" className="btn btn--accent" disabled title="Use inbox pipeline from toolbar">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="2" aria-hidden>
            <path d="m14 2-6 6M14 2 9 14l-1-6-6-1L14 2z" />
          </svg>
          Send via LinkedIn
        </button>
        <button type="button" className="btn btn--ghost" disabled>
          Regenerate
        </button>
      </div>
    </div>
  );
}
