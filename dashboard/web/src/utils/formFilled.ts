import type { ApplicationDetail, ApplyFormFilled, FormFieldSnapshot } from "../api";

function resumeRowFromMeta(meta: ApplyFormFilled | null | undefined): FormFieldSnapshot | null {
  const path = meta?.resume_pdf?.trim();
  if (!path) {
    return null;
  }
  const base = path.split("/").pop() ?? path;
  const hasDedicated = (meta?.fields ?? []).some((row) => {
    if (row.type !== "file") {
      return false;
    }
    const label = (row.label ?? "").toLowerCase();
    const value = (row.value ?? "").trim();
    return (
      label.includes("resume") ||
      label.includes("cv") ||
      value.includes(path) ||
      (base.length > 0 && value.includes(base))
    );
  });
  if (hasDedicated) {
    return null;
  }
  return {
    label: "Resume (PDF)",
    value: path,
    type: "file",
    empty: false,
    source: "apply",
  };
}

export function resolvedFormFields(detail: ApplicationDetail | null): FormFieldSnapshot[] {
  const meta = detail?.form_filled ?? detail?.log_detail?.parsed?.form_filled ?? null;
  const stored = meta?.fields;
  const fields =
    stored && stored.length > 0 ? [...stored] : [...(detail?.log_detail?.parsed?.fields ?? [])];
  const resumeRow = resumeRowFromMeta(meta);
  if (resumeRow) {
    fields.unshift(resumeRow);
  }
  return fields;
}

export function formFieldCount(detail: ApplicationDetail | null): number {
  return resolvedFormFields(detail).length;
}

export function hasStoredFormValues(app: {
  form_filled?: { field_count?: number; fields?: FormFieldSnapshot[]; resume_pdf?: string | null } | null;
  apply_log_path?: string | null;
}): boolean {
  const count = app.form_filled?.field_count ?? app.form_filled?.fields?.length ?? 0;
  return count > 0 || Boolean(app.form_filled?.resume_pdf) || Boolean(app.apply_log_path);
}
