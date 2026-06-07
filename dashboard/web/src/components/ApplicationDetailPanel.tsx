import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Application, ApplicationDetail, FormFieldSnapshot } from "../api";
import { resolvedFormFields } from "../utils/formFilled";
import {
  fetchApplicationDetail,
  fetchConfirmApplication,
  fetchMarkApplicationApplied,
} from "../api";
import {
  ApplicationRowActions,
  type ApplyListActionInfo,
} from "./ApplicationRowActions";
import {
  canRequeueApply,
  formatDurationMs,
  formatWhen,
  needsHumanIntervention,
  parseApplyErrorReasons,
  statusLabel,
} from "../utils/applicationAudit";
import { statusbarClass } from "../utils/statusbar";
import { companyInitials, companyLabelFromSite } from "../utils/jobFacts";

type Props = {
  app: Application | null;
  onApplyListAction?: (info: ApplyListActionInfo) => void;
};

// Outcome + form values answer "am I done / what was filled" — open by default.
// Proof, agent actions, and the raw log are reference detail — collapsed.
const DEFAULT_OPEN_SECTIONS: Record<string, boolean> = { outcome: true, form: true };

export function ApplicationDetailPanel({ app, onApplyListAction }: Props) {
  const queryClient = useQueryClient();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSec, setOpenSec] = useState<Record<string, boolean>>(DEFAULT_OPEN_SECTIONS);
  const toggleSec = (id: string) =>
    setOpenSec((prev) => ({ ...prev, [id]: !prev[id] }));

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
    setOpenSec(DEFAULT_OPEN_SECTIONS);
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

  const markAppliedMut = useMutation({
    mutationFn: () => fetchMarkApplicationApplied(app!.url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  if (!app) {
    return (
      <aside className="app-detail app-detail--empty" aria-label="Application details">
        <div className="app-detail__empty">
          <div className="app-detail__empty-icon" aria-hidden>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path
                strokeLinecap="round"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          </div>
          <p className="app-detail__empty-title">Select an application</p>
          <p className="app-detail__empty-sub">
            Pick a row to review outcome, form values, and what the agent did.
          </p>
        </div>
      </aside>
    );
  }

  const status = app.apply_status ?? "unknown";
  const isUnverified = status === "submitted_unverified";
  const canMarkApplied = status === "manual" || status === "failed";
  const showApplyActions = canRequeueApply(app) || isUnverified;
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

  const hasOutcome =
    Boolean(parsed?.result_line) ||
    Boolean(resultReason) ||
    dbReasons.length > 0 ||
    verificationReasons.length > 0 ||
    (parsed?.visible_errors?.length ?? 0) > 0;

  const company = companyLabelFromSite(app.site);
  const initials = companyInitials(company === "—" ? (app.title ?? "?") : company);

  return (
    <aside className="app-detail" aria-label="Application details">
      <header className="app-detail__hd">
        <div className="app-detail__brand">
          <span className="app-detail__logo" aria-hidden>
            {initials}
          </span>
          <div className="app-detail__brand-copy">
            <div className="app-detail__statusrow">
              <span className={statusbarClass(statusLabel(status))}>{statusLabel(status)}</span>
              {app.verification_confidence ? (
                <span className="app-detail__pill">Confidence {app.verification_confidence}</span>
              ) : null}
            </div>
            <h2 className="app-detail__title">{app.title ?? "Untitled"}</h2>
            <p className="app-detail__company">{company}</p>
          </div>
        </div>
        <div className="app-detail__links">
          {app.application_url ? (
            <a href={app.application_url} target="_blank" rel="noreferrer" className="app-detail__link">
              Application page
            </a>
          ) : null}
          <a href={app.url} target="_blank" rel="noreferrer" className="app-detail__link">
            Job posting
          </a>
        </div>
      </header>

      <div className="app-detail__facts">
        <div>
          <div className="fact__label">Fit score</div>
          <div className={app.fit_score != null && app.fit_score >= 8 ? "fact__value fact__value--acc" : "fact__value"}>
            {app.fit_score != null ? `${app.fit_score}/10` : "—"}
          </div>
        </div>
        <div>
          <div className="fact__label">Attempts</div>
          <div className="fact__value">{app.apply_attempts ?? 0}</div>
        </div>
        <div>
          <div className="fact__label">Applied</div>
          <div className="fact__value">{app.applied_at ? formatWhen(app.applied_at) : "—"}</div>
        </div>
        <div>
          <div className="fact__label">Last attempt</div>
          <div className="fact__value">
            {app.last_attempted_at ? formatWhen(app.last_attempted_at) : "—"}
          </div>
        </div>
        <div>
          <div className="fact__label">Duration</div>
          <div className="fact__value">{formatDurationMs(app.apply_duration_ms)}</div>
        </div>
      </div>

      <div className="app-detail__actions">
        {isUnverified ? (
          <button
            type="button"
            className="btn btn--accent"
            disabled={confirmMut.isPending}
            onClick={() => confirmMut.mutate()}
          >
            {confirmMut.isPending ? "Confirming…" : "Confirm applied"}
          </button>
        ) : null}
        {needsHumanIntervention(app) && canMarkApplied ? (
          <button
            type="button"
            className="btn"
            disabled={markAppliedMut.isPending}
            onClick={() => markAppliedMut.mutate()}
          >
            {markAppliedMut.isPending ? "Saving…" : "Mark applied"}
          </button>
        ) : null}
        {showApplyActions ? (
          <ApplicationRowActions
            app={app}
            layout="inline"
            onApplyListAction={onApplyListAction}
          />
        ) : null}
      </div>

      <div className="app-detail__body">
        {loading ? <p className="app-detail__state">Loading apply detail…</p> : null}
        {error ? <p className="app-detail__state app-detail__state--error">{error}</p> : null}

        <Section id="outcome" title="Outcome" open={Boolean(openSec.outcome)} onToggle={toggleSec}>
          {parsed?.result_line ? <p className="app-detail__lead">{parsed.result_line}</p> : null}
          {resultReason ? <p className="app-detail__warn-line">Agent: {resultReason}</p> : null}
          {dbReasons.length > 0 ? (
            <ul className="app-detail__bullets app-detail__bullets--warn">
              {dbReasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : null}
          {verificationReasons.length > 0 ? (
            <>
              <p className="app-detail__card-sub">Verification gaps</p>
              <ul className="app-detail__bullets app-detail__bullets--warn">
                {verificationReasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          ) : null}
          {parsed?.visible_errors?.length ? (
            <>
              <p className="app-detail__card-sub">Visible form errors</p>
              <ul className="app-detail__bullets app-detail__bullets--bad">
                {parsed.visible_errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          ) : null}
          {!hasOutcome && !loading ? (
            <p className="app-detail__muted">No structured outcome recorded.</p>
          ) : null}
        </Section>

        {formFields.length > 0 ? (
          <Section
            id="form"
            title="Form values filled"
            badge={formFields.length}
            open={Boolean(openSec.form)}
            onToggle={toggleSec}
          >
            {formMeta?.form_url ? (
              <p className="app-detail__muted app-detail__muted--break">{formMeta.form_url}</p>
            ) : null}
            <p className="app-detail__hint">Captured at apply time from the browser snapshot.</p>
            {formMeta?.empty_required != null && Number(formMeta.empty_required) > 0 ? (
              <p className="app-detail__warn-line">
                Empty required at verify: {String(formMeta.empty_required)}
              </p>
            ) : null}
            <FormValuesTable fields={formFields} />
          </Section>
        ) : !loading ? (
          <p className="app-detail__muted app-detail__muted--inset">
            No structured form values were saved. Open the raw log below if the agent ran field fills.
          </p>
        ) : null}

        {parsed?.verification || parsed?.result_json ? (
          <Section
            id="proof"
            title="Submit proof"
            open={Boolean(openSec.proof)}
            onToggle={toggleSec}
          >
            <dl className="app-detail__proof-grid">
              <ProofRow label="Decision" value={parsed.verification?.decision} />
              <ProofRow label="Submit button" value={parsed.verification?.submit_button_text} />
              <ProofRow label="Confirmation" value={parsed.verification?.confirmation_copy} />
              <ProofRow label="Pre-submit URL" value={parsed.verification?.pre_submit_url} />
              <ProofRow label="Post-submit URL" value={parsed.verification?.post_submit_url} />
              <ProofRow label="Screenshot" value={parsed.verification?.screenshot_path} />
            </dl>
          </Section>
        ) : null}

        {parsed?.fill_actions?.length ? (
          <Section
            id="actions"
            title="Agent actions"
            badge={parsed.fill_actions.length}
            open={Boolean(openSec.actions)}
            onToggle={toggleSec}
          >
            <ol className="app-detail__actions-log">
              {parsed.fill_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ol>
          </Section>
        ) : null}

        {detail?.tailored_resume_path || detail?.log_detail?.log_excerpt ? (
          <Section
            id="log"
            title="Resume & raw log"
            open={Boolean(openSec.log)}
            onToggle={toggleSec}
          >
            {detail?.tailored_resume_path ? (
              <p className="app-detail__mono app-detail__mono--break">
                {detail.tailored_resume_path}
              </p>
            ) : null}
            {detail?.log_detail?.log_path ? (
              <p className="app-detail__mono app-detail__mono--break app-detail__mono--dim">
                {detail.log_detail.log_path}
              </p>
            ) : null}
            {detail?.log_detail?.log_excerpt ? (
              <pre className="app-detail__log">{detail.log_detail.log_excerpt}</pre>
            ) : null}
          </Section>
        ) : null}
      </div>
    </aside>
  );
}

function Section({
  id,
  title,
  badge,
  open,
  onToggle,
  children,
}: {
  id: string;
  title: string;
  badge?: number;
  open: boolean;
  onToggle: (id: string) => void;
  children: ReactNode;
}) {
  return (
    <section className={open ? "app-detail__sect app-detail__sect--open" : "app-detail__sect"}>
      <button
        type="button"
        className="app-detail__sect-head"
        onClick={() => onToggle(id)}
        aria-expanded={open}
      >
        <span>{title}</span>
        {badge != null ? <span className="app-detail__sect-badge">{badge}</span> : null}
        <span className="app-detail__sect-chev" aria-hidden>
          ▶
        </span>
      </button>
      {open ? <div className="app-detail__sect-body">{children}</div> : null}
    </section>
  );
}

function FormValuesTable({ fields }: { fields: FormFieldSnapshot[] }) {
  return (
    <div className="app-detail__table-wrap">
      <table className="app-detail__table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={`${f.label}-${i}`} className={f.empty ? "app-detail__table-row--empty" : ""}>
              <td>{f.label || "—"}</td>
              <td className="app-detail__table-value">{f.value || "—"}</td>
              <td>{f.type || "—"}</td>
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
    <div className="app-detail__proof-item">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
