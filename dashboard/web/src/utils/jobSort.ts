/** Jobs list sort — URL `sort` param maps to GET /api/jobs (see server jobs._SORT_ORDERS). */

export type JobSortField =
  | "activity"
  | "discovered"
  | "scored"
  | "score"
  | "title"
  | "apply_priority";

export type JobSortDir = "asc" | "desc";

const SORT_PARAM_TO_FIELD: Record<string, JobSortField> = {
  activity_desc: "activity",
  activity_asc: "activity",
  discovered_at_desc: "discovered",
  discovered_at_asc: "discovered",
  scored_at_desc: "scored",
  scored_at_asc: "scored",
  fit_score_desc: "score",
  fit_score_asc: "score",
  title_asc: "title",
  title_desc: "title",
  apply_priority: "apply_priority",
};

export function defaultJobSort(stage: string): string {
  return stage === "ready" ? "apply_priority" : "activity_desc";
}

export function parseJobSort(
  sortParam: string | null | undefined,
  stage: string,
): { field: JobSortField; dir: JobSortDir; apiSort: string } {
  const fallback = defaultJobSort(stage);
  const apiSort = sortParam?.trim() || fallback;
  const field = SORT_PARAM_TO_FIELD[apiSort] ?? SORT_PARAM_TO_FIELD[fallback] ?? "activity";
  if (field === "apply_priority") {
    return { field, dir: "desc", apiSort: "apply_priority" };
  }
  const dir: JobSortDir = apiSort.endsWith("_asc") ? "asc" : "desc";
  return { field, dir, apiSort };
}

export function composeJobSort(field: JobSortField, dir: JobSortDir): string {
  if (field === "apply_priority") return "apply_priority";
  switch (field) {
    case "activity":
      return dir === "asc" ? "activity_asc" : "activity_desc";
    case "discovered":
      return dir === "asc" ? "discovered_at_asc" : "discovered_at_desc";
    case "scored":
      return dir === "asc" ? "scored_at_asc" : "scored_at_desc";
    case "score":
      return dir === "asc" ? "fit_score_asc" : "fit_score_desc";
    case "title":
      return dir === "asc" ? "title_asc" : "title_desc";
    default:
      return "activity_desc";
  }
}

export function jobSortFieldLabel(field: JobSortField): string {
  switch (field) {
    case "activity":
      return "Last activity";
    case "discovered":
      return "Discovered";
    case "scored":
      return "Scored";
    case "score":
      return "Fit score";
    case "title":
      return "Title";
    case "apply_priority":
      return "Apply priority";
    default:
      return "Sort";
  }
}

export function jobSortDirOptions(field: JobSortField): { value: JobSortDir; label: string }[] {
  if (field === "apply_priority") {
    return [{ value: "desc", label: "Best first" }];
  }
  if (field === "score") {
    return [
      { value: "desc", label: "High → low" },
      { value: "asc", label: "Low → high" },
    ];
  }
  if (field === "title") {
    return [
      { value: "asc", label: "A → Z" },
      { value: "desc", label: "Z → A" },
    ];
  }
  return [
    { value: "desc", label: "Newest first" },
    { value: "asc", label: "Oldest first" },
  ];
}

export function jobSortFieldOptions(stage: string): JobSortField[] {
  const base: JobSortField[] = ["activity", "discovered", "scored", "score", "title"];
  if (stage === "ready") {
    return ["apply_priority", ...base];
  }
  return base;
}
