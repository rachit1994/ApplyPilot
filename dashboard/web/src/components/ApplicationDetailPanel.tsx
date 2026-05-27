import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Application, ApplicationDetail, FormFieldSnapshot } from "../api";
import { resolvedFormFields } from "../utils/formFilled";
import {
  fetchApplicationDetail,
  fetchConfirmApplication,
  fetchMarkApplicationApplied,
  fetchRequeueApplication,
  fetchRetryApplication,
} from "../api";
import {
  formatWhen,
  needsHumanIntervention,
  parseApplyErrorReasons,
  statusChipClass,
  statusLabel,
} from "../utils/applicationAudit";

type Props = {
  app: Application | null;
};

export function ApplicationDetailPanel({ app }: Props) {
  const queryClient = useQueryClient();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    if (!app?.url) {
      setDetail(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    setShowLog(false);
    fetchApplicationDetail(app.url)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load detail");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [app?.url]);

  const confirmMut = useMutation({
    mutationFn: () => fetchConfirmApplication(app!.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const retryMut = useMutation({
    mutationFn: () => fetchRetryApplication(app!.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const markAppliedMut = useMutation({
    mutationFn: () => fetchMarkApplicationApplied(app!.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const requeueMut = useMutation({
    mutationFn: () => fetchRequeueApplication(app!.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  if (!app) {
    return (
      <div className="flex h-full min-h-[50vh] items-center justify-center rounded-card border border-panel-border bg-panel p-8 text-sm text-ink-3">
        Select an application to see filled fields, failure reasons, and logs.
      </div>
    );
  }

  const status = app.apply_status ?? "unknown";
  const isUnverified = status === "submitted_unverified";
  const canMarkApplied = status === "manual" || status === "failed";
  const canRequeue = status === "manual" || status === "failed";
  const parsed = detail?.log_detail?.parsed;
  const detailFields = resolvedFormFields(detail);
  const formFields =
    detailFields.length > 0 ? detailFields : (app.form_filled?.fields ?? []);
  const formMeta = detail?.form_filled ?? app.form_filled ?? parsed?.form_filled ?? null;
  const dbReasons = parseApplyErrorReasons(app.apply_error);
  const verificationReasons = parsed?.verification?.reasons ?? [];
  const resultReason =
    parsed?.result_json?.reason ??
    (parsed?.result_line?.includes(":") ? parsed.result_line.split(":").slice(2).join(":") : null);

  return (
    <div className="flex h-full min-h-[50vh] flex-col rounded-card border border-panel-border bg-panel">
      <header className="border-b border-panel-border px-4 py-3">
        <div className="flex flex-wrap items-start gap-2">
          <span
            className={`shrink-0 rounded-chip px-2 py-0.5 text-[10px] font-medium uppercase ${statusChipClass(status)}`}
          >
            {statusLabel(status)}
          </span>
          {app.verification_confidence ? (
            <span className="text-[10px] text-ink-4">conf {app.verification_confidence}</span>
          ) : null}
        </div>
        <h2 className="mt-2 font-display text-lg text-ink">{app.title ?? "Untitled"}</h2>
        <p className="mt-1 text-xs text-ink-3">
          {app.site ?? "—"}
          {app.fit_score != null ? ` · fit ${app.fit_score}` : null}
          {app.applied_at ? ` · applied ${formatWhen(app.applied_at)}` : null}
          {app.last_attempted_at ? ` · tried ${formatWhen(app.last_attempted_at)}` : null}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {app.application_url ? (
            <a
              href={app.application_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-btn border border-panel-border px-3 py-1 text-xs text-accent hover:bg-panel-elevated"
            >
              Open application
            </a>
          ) : null}
          <a
            href={app.url}
            target="_blank"
            rel="noreferrer"
            className="rounded-btn border border-panel-border px-3 py-1 text-xs text-ink-2 hover:bg-panel-elevated"
          >
            Job URL
          </a>
          {needsHumanIntervention(app) && canMarkApplied ? (
            <button
              type="button"
              disabled={markAppliedMut.isPending}
              onClick={() => markAppliedMut.mutate()}
              className="rounded-btn bg-good/15 px-3 py-1 text-xs text-good hover:bg-good/25 disabled:opacity-50"
            >
              Mark applied
            </button>
          ) : null}
          {needsHumanIntervention(app) && canRequeue ? (
            <button
              type="button"
              disabled={requeueMut.isPending}
              onClick={() => requeueMut.mutate()}
              className="rounded-btn bg-warn/15 px-3 py-1 text-xs text-warn hover:bg-warn/25 disabled:opacity-50"
            >
              Re-queue
            </button>
          ) : null}
          {isUnverified ? (
            <>
              <button
                type="button"
                disabled={confirmMut.isPending}
                onClick={() => confirmMut.mutate()}
                className="rounded-btn bg-good/15 px-3 py-1 text-xs text-good hover:bg-good/25 disabled:opacity-50"
              >
                Confirm applied
              </button>
              <button
                type="button"
                disabled={retryMut.isPending}
                onClick={() => retryMut.mutate()}
                className="rounded-btn bg-warn/15 px-3 py-1 text-xs text-warn hover:bg-warn/25 disabled:opacity-50"
              >
                Retry apply
              </button>
            </>
          ) : null}
        </div>
      </header>

      <div className="scroll-thin flex-1 space-y-5 overflow-y-auto p-4 text-sm">
        {loading ? <p className="text-ink-3">Loading apply detail…</p> : null}
        {error ? <p className="text-bad">{error}</p> : null}

        <section>
          <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Outcome</h3>
          {parsed?.result_line ? (
            <p className="mt-2 font-mono text-xs text-ink-2">{parsed.result_line}</p>
          ) : null}
          {resultReason ? (
            <p className="mt-2 text-xs text-warn">Agent reason: {resultReason}</p>
          ) : null}
          {dbReasons.length > 0 ? (
            <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-warn">
              {dbReasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : null}
          {verificationReasons.length > 0 ? (
            <>
              <p className="mt-3 text-[10px] font-medium uppercase tracking-wide text-ink-4">
                Verification gaps
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-warn">
                {verificationReasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          ) : null}
          {parsed?.visible_errors?.length ? (
            <>
              <p className="mt-3 text-[10px] font-medium uppercase tracking-wide text-ink-4">
                Visible form errors
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-bad">
                {parsed.visible_errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          ) : null}
        </section>

        {parsed?.verification || parsed?.result_json ? (
          <section>
            <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
              Submit proof
            </h3>
            <dl className="mt-2 grid gap-2 text-xs">
              <ProofRow label="Decision" value={parsed.verification?.decision} />
              <ProofRow label="Submit button" value={parsed.verification?.submit_button_text} />
              <ProofRow label="Submit ref" value={parsed.verification?.submit_click_ref} />
              <ProofRow label="Pre-submit URL" value={parsed.verification?.pre_submit_url} />
              <ProofRow label="Post-submit URL" value={parsed.verification?.post_submit_url} />
              <ProofRow label="Confirmation" value={parsed.verification?.confirmation_copy} />
              <ProofRow label="Screenshot" value={parsed.verification?.screenshot_path} />
              <ProofRow
                label="Verification code"
                value={parsed.verification?.verification_code_used}
              />
            </dl>
          </section>
        ) : null}

        {formFields.length > 0 ? (
          <section>
            <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
              Form values filled
              {formMeta?.form_url ? (
                <span className="ml-2 font-normal normal-case text-ink-4">{formMeta.form_url}</span>
              ) : null}
            </h3>
            <p className="mt-1 text-[10px] text-ink-4">
              Saved at apply time from browser snapshot and agent fill actions (not just raw log).
            </p>
            {formMeta?.empty_required != null && Number(formMeta.empty_required) > 0 ? (
              <p className="mt-2 text-xs text-warn">
                Empty required at verify: {String(formMeta.empty_required)}
              </p>
            ) : null}
            <FormValuesTable fields={formFields} />
          </section>
        ) : (
          <p className="text-xs text-ink-3">
            No structured form values were captured for this attempt. Check the raw log below if the
            agent ran VERIFY PAGE STATE or browser_fill lines.
          </p>
        )}

        {parsed?.fill_actions?.length ? (
          <section>
            <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">
              Agent actions
            </h3>
            <ol className="mt-2 max-h-40 space-y-1 overflow-y-auto font-mono text-[10px] text-ink-3">
              {parsed.fill_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ol>
          </section>
        ) : null}

        {detail?.tailored_resume_path ? (
          <section>
            <h3 className="text-[10px] font-medium uppercase tracking-wide text-ink-4">Resume</h3>
            <p className="mt-1 break-all font-mono text-xs text-ink-2">{detail.tailored_resume_path}</p>
          </section>
        ) : null}

        {detail?.log_detail?.log_excerpt ? (
          <section>
            <button
              type="button"
              onClick={() => setShowLog((v) => !v)}
              className="text-[10px] font-medium uppercase tracking-wide text-accent hover:underline"
            >
              {showLog ? "Hide" : "Show"} raw log
            </button>
            {detail.log_detail.log_path ? (
              <p className="mt-1 break-all font-mono text-[10px] text-ink-4">
                {detail.log_detail.log_path}
              </p>
            ) : null}
            {showLog ? (
              <pre className="mt-2 max-h-64 overflow-auto rounded border border-panel-border bg-canvas p-2 font-mono text-[10px] text-ink-3">
                {detail.log_detail.log_excerpt}
              </pre>
            ) : null}
          </section>
        ) : null}
      </div>
    </div>
  );
}

function FormValuesTable({ fields }: { fields: FormFieldSnapshot[] }) {
  return (
    <div className="mt-2 overflow-hidden rounded border border-panel-border">
      <table className="w-full text-left text-xs">
        <thead className="bg-panel-elevated text-[10px] uppercase tracking-wide text-ink-4">
          <tr>
            <th className="px-2 py-1.5 font-medium">Field</th>
            <th className="px-2 py-1.5 font-medium">Value filled</th>
            <th className="px-2 py-1.5 font-medium">Type</th>
            <th className="px-2 py-1.5 font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr
              key={`${f.label}-${i}`}
              className={f.empty ? "bg-warn/5" : "border-t border-panel-border"}
            >
              <td className="px-2 py-1.5 text-ink-4">{f.label || "—"}</td>
              <td className={`px-2 py-1.5 font-mono whitespace-pre-wrap break-all ${f.empty ? "text-warn" : "text-ink"}`}>
                {f.value || "—"}
              </td>
              <td className="px-2 py-1.5 text-ink-3">{f.type || "—"}</td>
              <td className="px-2 py-1.5 text-ink-3">{f.source ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProofRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-ink-4">{label}</dt>
      <dd className="mt-0.5 break-all font-mono text-ink-2">{value}</dd>
    </div>
  );
}
