import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchLearningClusters,
  fetchLearningReview,
  fetchLearningStats,
  postLearningBan,
  postLearningPromote,
  type LearningCluster,
} from "../api";
import { PageCanvas } from "./layout/PageCanvas";

export function LearningDashboardPage() {
  const queryClient = useQueryClient();

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["learning", "stats"],
    queryFn: () => fetchLearningStats(24),
    refetchInterval: 15_000,
  });

  const { data: review, isLoading: reviewLoading } = useQuery({
    queryKey: ["learning", "review"],
    queryFn: () => fetchLearningReview(40),
    refetchInterval: 15_000,
  });

  const { data: clusters, isLoading: clustersLoading } = useQuery({
    queryKey: ["learning", "clusters"],
    queryFn: () => fetchLearningClusters(15),
    refetchInterval: 15_000,
  });

  const promoteMut = useMutation({
    mutationFn: ({ sig, scope }: { sig: string; scope: string }) =>
      postLearningPromote(sig, scope),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["learning"] });
    },
  });

  const banMut = useMutation({
    mutationFn: ({ sig, scope }: { sig: string; scope: string }) => postLearningBan(sig, scope),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["learning"] });
    },
  });

  const trusted = stats?.nav_playbook.by_status?.trusted ?? 0;
  const trial = stats?.nav_playbook.by_status?.trial ?? 0;
  const replayPct = stats?.cache_hit.replay_pct ?? 0;

  return (
    <PageCanvas wide>
      <div className="today">
        <div className="today__hero">
          <div className="summary">
            <div className="summary__count">
              {statsLoading ? "…" : String(stats?.nav_playbook.total ?? 0)}
            </div>
            <div className="summary__label">Nav playbook rows</div>
            <div className="summary__sub">
              {statsLoading ? "Loading…" : `${trusted} trusted · ${trial} trial`}
            </div>
          </div>

          <div className="summary summary--primary">
            <div className="summary__count">{statsLoading ? "…" : `${replayPct}%`}</div>
            <div className="summary__label">Cache replay (24h)</div>
            <div className="summary__sub">
              {statsLoading
                ? "Loading…"
                : `${stats?.cache_hit.replay_count ?? 0} replay · ${stats?.cache_hit.llm_count ?? 0} LLM`}
            </div>
          </div>

          <div className="summary">
            <div className="summary__count">
              {statsLoading ? "…" : String(stats?.field_strategy_total ?? 0)}
            </div>
            <div className="summary__label">Field strategies</div>
            <div className="summary__sub">Cached fill methods per field signature</div>
          </div>
        </div>

        <div className="pipeline__grid" style={{ marginTop: 16 }}>
          <div className="panel" style={{ gridColumn: "1 / -1" }}>
            <div className="panel__head panel__head--inset">
              <div>
                <div className="panel__title">Review timeline</div>
                <div className="panel__sub">Recent unblock and fill decisions</div>
              </div>
            </div>
            <div className="panel__body panel__body--tight">
              {reviewLoading ? (
                <p className="panel__sub" style={{ padding: 12 }}>
                  Loading review log…
                </p>
              ) : (review?.events.length ?? 0) === 0 ? (
                <p className="panel__sub" style={{ padding: 12 }}>
                  No review events yet. Run apply with unblock learning enabled.
                </p>
              ) : (
                <div className="devlog" role="list">
                  {review?.events.map((ev) => (
                    <div key={ev.id} className="devlog__row" role="listitem">
                      <div className="devlog__ts">{formatTs(ev.ts)}</div>
                      <div className="devlog__stage">{ev.tier ?? ev.action_type ?? "—"}</div>
                      <div className="devlog__msg">
                        {ev.outcome ?? "—"}
                        {ev.ats_family ? ` · ${ev.ats_family}` : ""}
                        {ev.state_sig ? ` · ${shortSig(ev.state_sig)}` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="panel" style={{ gridColumn: "1 / -1" }}>
            <div className="panel__head panel__head--inset">
              <div>
                <div className="panel__title">Dedupe clusters</div>
                <div className="panel__sub">Repeated state signatures — promote trusted or ban bad recipes</div>
              </div>
            </div>
            <div className="panel__body panel__body--tight">
              {clustersLoading ? (
                <p className="panel__sub" style={{ padding: 12 }}>
                  Loading clusters…
                </p>
              ) : (clusters?.clusters.length ?? 0) === 0 ? (
                <p className="panel__sub" style={{ padding: 12 }}>
                  No clusters yet.
                </p>
              ) : (
                clusters?.clusters.map((row) => (
                  <ClusterRow
                    key={row.state_sig}
                    row={row}
                    busy={promoteMut.isPending || banMut.isPending}
                    onPromote={() =>
                      promoteMut.mutate({ sig: row.state_sig, scope: "host" })
                    }
                    onBan={() => banMut.mutate({ sig: row.state_sig, scope: "host" })}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </PageCanvas>
  );
}

function ClusterRow({
  row,
  busy,
  onPromote,
  onBan,
}: {
  row: LearningCluster;
  busy: boolean;
  onPromote: () => void;
  onBan: () => void;
}) {
  return (
    <div className="src-row" style={{ alignItems: "center" }}>
      <div className="src__name" style={{ flex: 1, minWidth: 0 }}>
        <div title={row.state_sig}>{shortSig(row.state_sig)}</div>
        <small>
          {row.count}× · {row.ats_family ?? "—"} · {row.action_type ?? "—"} · {row.outcome ?? "—"}
        </small>
      </div>
      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <button type="button" className="btn btn--ghost" disabled={busy} onClick={onPromote}>
          Promote
        </button>
        <button type="button" className="btn btn--ghost" disabled={busy} onClick={onBan}>
          Ban
        </button>
      </div>
    </div>
  );
}

function shortSig(sig: string): string {
  if (sig.length <= 24) return sig;
  return `${sig.slice(0, 10)}…${sig.slice(-8)}`;
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts.slice(0, 16);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts.slice(0, 16);
  }
}
