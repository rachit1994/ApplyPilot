import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchApplicationDetail,
  fetchApplications,
  type Application,
  type ApplicationDetail,
} from "../api";
import { formatDuration, formatTime } from "../utils/format";

function statusBadge(status: string | null, error: string | null) {
  if (status === "applied") {
    return <span className="rounded bg-emerald-950/50 px-2 py-0.5 text-emerald-300">Applied</span>;
  }
  if (status === "failed") {
    return <span className="rounded bg-red-950/50 px-2 py-0.5 text-red-300">Failed</span>;
  }
  if (status === "manual") {
    return <span className="rounded bg-amber-950/50 px-2 py-0.5 text-amber-300">Manual</span>;
  }
  if (error) {
    return <span className="rounded bg-red-950/50 px-2 py-0.5 text-red-300">Error</span>;
  }
  return <span className="text-zinc-500">{status ?? "—"}</span>;
}

function DetailPanel({ detail }: { detail: ApplicationDetail }) {
  const parsed = detail.log_detail?.parsed;
  const fields = parsed?.fields ?? [];

  return (
    <div className="mt-3 space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-zinc-500">Applied</p>
          <p className="text-zinc-200">{formatTime(detail.applied_at)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-zinc-500">Duration</p>
          <p className="text-zinc-200">
            {detail.apply_duration_ms != null
              ? formatDuration(detail.apply_duration_ms)
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-zinc-500">Application URL</p>
          {detail.application_url ? (
            <a
              href={detail.application_url}
              target="_blank"
              rel="noreferrer"
              className="break-all text-blue-400 hover:underline"
            >
              {detail.application_url}
            </a>
          ) : (
            <p className="text-zinc-400">—</p>
          )}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-zinc-500">Result</p>
          <p className="font-mono text-xs text-zinc-300">
            {parsed?.result_line ?? detail.apply_status ?? "—"}
          </p>
        </div>
      </div>

      {detail.apply_error && (
        <div className="rounded border border-red-900/50 bg-red-950/30 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-red-400">Error</p>
          <p className="mt-1 text-sm text-red-200">{detail.apply_error}</p>
        </div>
      )}

      {parsed?.fill_actions && parsed.fill_actions.length > 0 && (
        <div>
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Agent actions (form fills & uploads)
          </p>
          <ul className="max-h-40 space-y-1 overflow-y-auto font-mono text-xs text-zinc-400">
            {parsed.fill_actions.map((action) => (
              <li key={action}>• {action}</li>
            ))}
          </ul>
        </div>
      )}

      {fields.length > 0 && (
        <div>
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            Last captured form snapshot
          </p>
          {parsed?.form_url && (
            <p className="mb-2 truncate text-xs text-zinc-500">{parsed.form_url}</p>
          )}
          <div className="scroll-thin max-h-56 overflow-y-auto rounded border border-zinc-800">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-zinc-900 text-zinc-500">
                <tr>
                  <th className="px-3 py-2">Field</th>
                  <th className="px-3 py-2">Value</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((field, i) => (
                  <tr key={`${field.label}-${i}`} className="border-t border-zinc-800/80">
                    <td className="px-3 py-2 text-zinc-400">{field.label || "—"}</td>
                    <td
                      className={`px-3 py-2 font-mono ${
                        field.empty ? "text-amber-400" : "text-zinc-200"
                      }`}
                    >
                      {field.value || (field.empty ? "(empty)" : "—")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(parsed?.visible_errors?.length ?? 0) > 0 && (
            <div className="mt-2 rounded border border-amber-900/40 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
              Page errors: {parsed?.visible_errors?.join(" · ")}
            </div>
          )}
        </div>
      )}

      {!fields.length && !parsed?.fill_actions?.length && !detail.apply_error && (
        <p className="text-xs text-zinc-500">
          No form snapshot in the apply log yet. New apply runs store session logs under
          ~/.applypilot/logs; older runs may only show status and error from the database.
        </p>
      )}

      {detail.log_detail?.log_excerpt && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300">
            Raw log excerpt
          </summary>
          <pre className="scroll-thin mt-2 max-h-48 overflow-auto rounded bg-zinc-950 p-3 font-mono text-[10px] leading-relaxed text-zinc-500">
            {detail.log_detail.log_excerpt}
          </pre>
        </details>
      )}
    </div>
  );
}

export function ApplicationsPage() {
  const [includeFailed, setIncludeFailed] = useState(false);
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["applications", includeFailed],
    queryFn: () => fetchApplications({ limit: 200, include_failed: includeFailed }),
  });

  const { data: detail } = useQuery({
    queryKey: ["application-detail", selectedUrl],
    queryFn: () => fetchApplicationDetail(selectedUrl!),
    enabled: Boolean(selectedUrl),
  });

  const applications = useMemo(() => data?.applications ?? [], [data]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <header className="shrink-0">
        <h2 className="text-lg font-semibold text-zinc-100">Applications</h2>
        <p className="mt-0.5 text-sm text-zinc-500">
          Jobs you applied to — form values and errors from apply session logs.
        </p>
      </header>

      <div className="flex shrink-0 items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input
            type="checkbox"
            checked={includeFailed}
            onChange={(e) => {
              setIncludeFailed(e.target.checked);
              setSelectedUrl(null);
            }}
            className="rounded border-zinc-600"
          />
          Include failed attempts
        </label>
        <span className="text-[10px] text-zinc-600">{data?.total ?? 0} total</span>
      </div>

      <div className="panel flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          {isLoading && <p className="p-4 text-sm text-zinc-500">Loading applications…</p>}
          {!isLoading && applications.length === 0 && (
            <p className="p-8 text-center text-sm text-zinc-500">
              No applications yet. Run <span className="font-mono">applypilot apply</span> to
              populate this list.
            </p>
          )}
          {!isLoading &&
            applications.map((app) => (
              <ApplicationRowItem
                key={app.url}
                app={app}
                expanded={selectedUrl === app.url}
                onToggle={() =>
                  setSelectedUrl((current) => (current === app.url ? null : app.url))
                }
                detail={selectedUrl === app.url ? detail : undefined}
              />
            ))}
        </div>
      </div>
    </div>
  );
}

function ApplicationRowItem({
  app,
  expanded,
  onToggle,
  detail,
}: {
  app: Application;
  expanded: boolean;
  onToggle: () => void;
  detail?: ApplicationDetail;
}) {
  const when = app.applied_at ?? app.last_attempted_at;

  return (
    <article className="border-b border-zinc-800/80">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-4 px-4 py-3 text-left hover:bg-zinc-800/30"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-zinc-100">{app.title ?? "Untitled"}</p>
          <p className="mt-0.5 text-xs text-zinc-500">
            {app.site ?? "—"}
            {app.location ? ` · ${app.location}` : ""}
          </p>
          {app.apply_error && !expanded && (
            <p className="mt-1 truncate text-xs text-red-300">{app.apply_error}</p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <p className="text-xs text-zinc-400">{formatTime(when)}</p>
          <div className="mt-1">{statusBadge(app.apply_status, app.apply_error)}</div>
        </div>
        <span className="mt-1 text-zinc-600">{expanded ? "▼" : "▶"}</span>
      </button>
      {expanded && detail && <div className="px-4 pb-4"><DetailPanel detail={detail} /></div>}
    </article>
  );
}
