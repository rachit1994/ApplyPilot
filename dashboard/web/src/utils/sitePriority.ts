/** Mirrors applypilot.discovery.site_priority — keep in sync with backend names. */

export const PRIORITY_BOARD_NAMES = ["LinkedIn", "Wellfound"] as const;

export const APPLY_QUEUE_ORDER_LABEL =
  "LinkedIn → Wellfound → ATS boards → other";

export function isPriorityBoardName(name: string | null | undefined): boolean {
  const lowered = (name ?? "").trim().toLowerCase();
  if (!lowered) return false;
  if (lowered === "linkedin" || lowered.includes("linkedin")) return true;
  if (lowered === "wellfound" || lowered.includes("wellfound")) return true;
  if (lowered.includes("angel.co")) return true;
  return PRIORITY_BOARD_NAMES.some((p) => p.toLowerCase() === lowered);
}

export function prioritySortKey(name: string | null | undefined): number {
  const lowered = (name ?? "").trim().toLowerCase();
  const idx = PRIORITY_BOARD_NAMES.findIndex((p) => p.toLowerCase() === lowered);
  if (idx >= 0) return idx;
  if (lowered.includes("linkedin")) return 0;
  if (lowered.includes("wellfound") || lowered.includes("angel.co")) return 1;
  return PRIORITY_BOARD_NAMES.length;
}

export function sortByPriorityName<T extends { source?: string; site?: string | null }>(
  rows: T[],
): T[] {
  return [...rows].sort((a, b) => {
    const keyA = prioritySortKey(a.source ?? a.site ?? "");
    const keyB = prioritySortKey(b.source ?? b.site ?? "");
    if (keyA !== keyB) return keyA - keyB;
    const labelA = (a.source ?? a.site ?? "").toLowerCase();
    const labelB = (b.source ?? b.site ?? "").toLowerCase();
    return labelA.localeCompare(labelB);
  });
}
