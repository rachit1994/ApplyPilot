/** Map pipeline / apply labels to finalized.html statusbar modifiers. */
export function statusbarClass(label: string): string {
  const s = label.toLowerCase();
  if (
    s.includes("fail") ||
    s.includes("manual") ||
    s.includes("error") ||
    s.includes("reject") ||
    s.includes("warn") ||
    s.includes("need") ||
    s.includes("claude")
  ) {
    return "statusbar statusbar--warn";
  }
  if (
    s.includes("applied") ||
    s.includes("submitted") ||
    s.includes("submit") ||
    s.includes("done") ||
    s.includes("ok")
  ) {
    return "statusbar statusbar--ok";
  }
  if (s.includes("tailored")) {
    return "statusbar";
  }
  if (s.includes("new") || s.includes("discover") || s.includes("score")) {
    return "statusbar statusbar--new";
  }
  return "statusbar";
}

export function formatJobAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const min = Math.floor(ms / 60_000);
  if (min < 60) return `${Math.max(1, min)}m`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}
