const API = "/api";

function isAbsoluteLocalPath(path: string): boolean {
  const p = path.trim();
  return p.startsWith("/") || /^[A-Za-z]:[\\/]/.test(p);
}

/** Build a file:// URL for an absolute path on this machine. */
export function toFileUrl(path: string): string {
  const normalized = path.trim().replace(/\\/g, "/");
  if (/^[A-Za-z]:\//.test(normalized)) {
    return `file:///${normalized.split("/").map(encodeURIComponent).join("/")}`;
  }
  const parts = normalized.split("/");
  return `file://${parts.map((seg) => (seg === "" ? "" : encodeURIComponent(seg))).join("/")}`;
}

/**
 * Open a local artifact (PDF, cover letter, etc.) in a new tab.
 * Absolute paths use file:// directly; relative paths go through the API redirect.
 */
export function artifactFileUrl(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) return "#";
  if (isAbsoluteLocalPath(trimmed)) {
    return toFileUrl(trimmed);
  }
  const q = new URLSearchParams({ path: trimmed });
  return `${API}/artifacts/file?${q}`;
}

export function artifactBasename(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) return "—";
  const parts = trimmed.split(/[/\\]/);
  return parts[parts.length - 1] || trimmed;
}
