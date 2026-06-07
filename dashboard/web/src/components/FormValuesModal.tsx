import type { ApplyFormFilled, FormFieldSnapshot } from "../api";
import { artifactBasename } from "../utils/artifacts";

type Props = {
  open: boolean;
  title: string;
  fields: FormFieldSnapshot[];
  formMeta: ApplyFormFilled | null;
  onClose: () => void;
  onSetDefault?: (label: string, value: string) => void | Promise<void>;
};

export function FormValuesModal({ open, title, fields, formMeta, onClose, onSetDefault }: Props) {
  if (!open) return null;

  return (
    <div
      className="run-plan-modal form-values-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="form-values-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="run-plan-modal__sheet run-plan-modal__sheet--wide form-values-modal__sheet"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="panel__head panel__head--inset run-plan-modal__head">
          <div>
            <h2 id="form-values-modal-title" className="panel__title">
              Form values filled
            </h2>
            <p className="panel__sub">{title}</p>
          </div>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="run-plan-modal__body form-values-modal__body">
          {formMeta?.form_url ? (
            <p className="app-detail__muted app-detail__muted--break">{formMeta.form_url}</p>
          ) : null}
          {formMeta?.empty_required != null && Number(formMeta.empty_required) > 0 ? (
            <p className="app-detail__warn-line">
              Empty required at verify: {String(formMeta.empty_required)}
            </p>
          ) : null}
          <div className="app-detail__table-wrap form-values-modal__table-wrap">
            <table className="app-detail__table form-values-modal__table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Type</th>
                  {onSetDefault ? <th aria-label="Actions" /> : null}
                </tr>
              </thead>
              <tbody>
                {fields.map((f, i) => (
                  <tr key={`${f.label}-${i}`} className={f.empty ? "app-detail__table-row--empty" : ""}>
                    <td>{f.label || "—"}</td>
                    <td className="app-detail__table-value form-values-modal__value">{f.value || "—"}</td>
                    <td>{f.type || "—"}</td>
                    {onSetDefault ? (
                      <td>
                        {f.label && f.value ? (
                          <button
                            type="button"
                            className="btn btn--sm btn--ghost"
                            onClick={() => void onSetDefault(f.label, f.value)}
                          >
                            Set default
                          </button>
                        ) : null}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {formMeta?.resume_pdf ? (
            <p className="form-values-modal__meta">
              Resume: {artifactBasename(formMeta.resume_pdf)}
            </p>
          ) : null}
          {formMeta?.cover_pdf ? (
            <p className="form-values-modal__meta">
              Cover letter: {artifactBasename(formMeta.cover_pdf)}
            </p>
          ) : null}
        </div>
        <footer className="run-plan-modal__foot">
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </footer>
      </div>
    </div>
  );
}
