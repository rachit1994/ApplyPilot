import type { ApplicationDetail, FormFieldSnapshot } from "../api";

export function resolvedFormFields(detail: ApplicationDetail | null): FormFieldSnapshot[] {
  const stored = detail?.form_filled?.fields;
  if (stored && stored.length > 0) {
    return stored;
  }
  return detail?.log_detail?.parsed?.fields ?? [];
}

export function formFieldCount(detail: ApplicationDetail | null): number {
  return resolvedFormFields(detail).length;
}

export function hasStoredFormValues(app: {
  form_filled?: { field_count?: number; fields?: FormFieldSnapshot[] } | null;
  apply_log_path?: string | null;
}): boolean {
  const count = app.form_filled?.field_count ?? app.form_filled?.fields?.length ?? 0;
  return count > 0 || Boolean(app.apply_log_path);
}
