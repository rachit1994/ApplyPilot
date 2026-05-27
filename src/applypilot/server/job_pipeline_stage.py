"""Pipeline stage labels and SQL filters aligned with dashboard jobPipeline.ts."""

from __future__ import annotations

from applypilot import config

MAX_APPLY_ATTEMPTS = int(config.DEFAULTS.get("max_apply_attempts", 3))
MAX_TAILOR_ATTEMPTS = 5

# Display labels (must match dashboard/web/src/utils/jobPipeline.ts).
STAGE_APPLIED = "Applied"
STAGE_APPLYING = "Applying"
STAGE_NEEDS_CHECK = "Needs check"
STAGE_MANUAL = "Manual"
STAGE_READY = "Ready"
STAGE_FAILED = "Failed"
STAGE_COVER = "Cover"
STAGE_TAILORED = "Tailored"
STAGE_TAILOR_EXHAUSTED = "Tailor exhausted"
STAGE_SCORED = "Scored"
STAGE_ENRICHED = "Enriched"
STAGE_ENRICH_ERROR = "Enrich error"
STAGE_DISCOVERED = "Discovered"

ALL_STAGE_LABELS: tuple[str, ...] = (
    STAGE_APPLIED,
    STAGE_APPLYING,
    STAGE_NEEDS_CHECK,
    STAGE_MANUAL,
    STAGE_READY,
    STAGE_FAILED,
    STAGE_COVER,
    STAGE_TAILORED,
    STAGE_TAILOR_EXHAUSTED,
    STAGE_SCORED,
    STAGE_ENRICHED,
    STAGE_ENRICH_ERROR,
    STAGE_DISCOVERED,
)

# URL / API slug -> display label
STAGE_SLUG_TO_LABEL: dict[str, str] = {
    "applied": STAGE_APPLIED,
    "applying": STAGE_APPLYING,
    "needs_check": STAGE_NEEDS_CHECK,
    "manual": STAGE_MANUAL,
    "ready": STAGE_READY,
    "failed": STAGE_FAILED,
    "cover": STAGE_COVER,
    "tailored": STAGE_TAILORED,
    "tailor_exhausted": STAGE_TAILOR_EXHAUSTED,
    "scored": STAGE_SCORED,
    "enriched": STAGE_ENRICHED,
    "enrich_error": STAGE_ENRICH_ERROR,
    "discovered": STAGE_DISCOVERED,
}

LABEL_TO_SLUG: dict[str, str] = {v: k for k, v in STAGE_SLUG_TO_LABEL.items()}


def _ready_sql(max_apply: int) -> str:
    return f"""(
        tailored_resume_path IS NOT NULL
        AND tailored_resume_path != ''
        AND applied_at IS NULL
        AND (apply_status IS NULL OR apply_status = 'failed')
        AND (apply_attempts IS NULL OR apply_attempts < {max_apply})
        AND (apply_status IS NULL OR apply_status NOT IN (
            'manual', 'in_progress', 'applied', 'submitted_unverified'
        ))
    )"""


def pipeline_stage_case_sql(
    *,
    max_apply_attempts: int = MAX_APPLY_ATTEMPTS,
    max_tailor_attempts: int = MAX_TAILOR_ATTEMPTS,
) -> str:
    """SQL CASE expression returning pipeline stage label for a jobs row."""
    ready = _ready_sql(max_apply_attempts)
    return f"""
    CASE
        WHEN apply_status = 'in_progress' THEN '{STAGE_APPLYING}'
        WHEN apply_status = 'submitted_unverified' THEN '{STAGE_NEEDS_CHECK}'
        WHEN apply_status = 'manual' THEN '{STAGE_MANUAL}'
        WHEN apply_status = 'applied'
             OR (applied_at IS NOT NULL AND apply_status IS NULL)
        THEN '{STAGE_APPLIED}'
        WHEN {ready} THEN '{STAGE_READY}'
        WHEN apply_status = 'failed' THEN '{STAGE_FAILED}'
        WHEN tailored_resume_path IS NOT NULL AND tailored_resume_path != ''
             AND cover_letter_path IS NOT NULL AND cover_letter_path != ''
        THEN '{STAGE_COVER}'
        WHEN tailored_resume_path IS NOT NULL AND tailored_resume_path != ''
        THEN '{STAGE_TAILORED}'
        WHEN fit_score IS NOT NULL
             AND COALESCE(tailor_attempts, 0) >= {max_tailor_attempts}
        THEN '{STAGE_TAILOR_EXHAUSTED}'
        WHEN fit_score IS NOT NULL THEN '{STAGE_SCORED}'
        WHEN full_description IS NOT NULL AND full_description != '' THEN '{STAGE_ENRICHED}'
        WHEN detail_error IS NOT NULL AND detail_error != '' THEN '{STAGE_ENRICH_ERROR}'
        ELSE '{STAGE_DISCOVERED}'
    END
    """


def resolve_stage_label(stage_param: str | None) -> str | None:
    """Map API stage slug or display label to canonical label."""
    if not stage_param or not stage_param.strip():
        return None
    raw = stage_param.strip()
    key = raw.lower().replace(" ", "_")
    if key in STAGE_SLUG_TO_LABEL:
        return STAGE_SLUG_TO_LABEL[key]
    if raw in ALL_STAGE_LABELS:
        return raw
    return None


def _has_tailored_sql() -> str:
    return "(tailored_resume_path IS NOT NULL AND tailored_resume_path != '')"


def _has_cover_sql() -> str:
    return "(cover_letter_path IS NOT NULL AND cover_letter_path != '')"


def stage_filter_clause(
    stage_label: str,
    *,
    max_apply_attempts: int = MAX_APPLY_ATTEMPTS,
    max_tailor_attempts: int = MAX_TAILOR_ATTEMPTS,
) -> str:
    """WHERE fragment matching pipeline stage (same priority as pipeline_stage_case_sql)."""
    ready = _ready_sql(max_apply_attempts)
    applied = "(apply_status = 'applied' OR (applied_at IS NOT NULL AND apply_status IS NULL))"
    applying = "(apply_status = 'in_progress')"
    needs_check = "(apply_status = 'submitted_unverified')"
    manual = "(apply_status = 'manual')"
    failed = "(apply_status = 'failed')"
    not_applied = "(applied_at IS NULL AND (apply_status IS NULL OR apply_status != 'applied'))"
    not_applying = "(apply_status IS NULL OR apply_status != 'in_progress')"
    not_needs_check = "(apply_status IS NULL OR apply_status != 'submitted_unverified')"
    not_manual = "(apply_status IS NULL OR apply_status != 'manual')"
    not_failed = "(apply_status IS NULL OR apply_status != 'failed')"
    tailored = _has_tailored_sql()
    not_tailored = "(tailored_resume_path IS NULL OR tailored_resume_path = '')"
    cover = _has_cover_sql()
    not_cover = "(cover_letter_path IS NULL OR cover_letter_path = '')"
    tailor_exhausted = (
        f"(fit_score IS NOT NULL AND COALESCE(tailor_attempts, 0) >= {max_tailor_attempts})"
    )
    not_tailor_exhausted = (
        f"(fit_score IS NULL OR COALESCE(tailor_attempts, 0) < {max_tailor_attempts})"
    )
    scored = (
        f"(fit_score IS NOT NULL AND COALESCE(tailor_attempts, 0) < {max_tailor_attempts})"
    )
    not_scored = (
        f"(fit_score IS NULL OR COALESCE(tailor_attempts, 0) >= {max_tailor_attempts})"
    )
    enriched = "(full_description IS NOT NULL AND full_description != '')"
    not_enriched = "(full_description IS NULL OR full_description = '')"
    enrich_error = "(detail_error IS NOT NULL AND detail_error != '')"
    not_enrich_error = "(detail_error IS NULL OR detail_error = '')"

    before_ready = f"{not_applied} AND {not_applying} AND {not_needs_check} AND {not_manual}"
    before_failed = f"{before_ready} AND NOT ({ready})"
    before_cover = f"{before_failed} AND {not_failed}"
    before_tailored = f"{before_cover} AND NOT ({tailored} AND {cover})"
    before_tailor_exhausted = f"{before_tailored} AND {not_tailored}"
    before_scored = f"{before_tailor_exhausted} AND {not_tailor_exhausted}"
    before_enriched = f"{before_scored} AND {not_scored}"
    before_enrich_error = f"{before_enriched} AND {not_enriched}"

    predicates: dict[str, str] = {
        STAGE_APPLIED: applied,
        STAGE_APPLYING: applying,
        STAGE_NEEDS_CHECK: needs_check,
        STAGE_MANUAL: manual,
        STAGE_READY: f"({ready})",
        STAGE_FAILED: f"({failed} AND NOT ({ready}))",
        STAGE_COVER: f"({before_cover} AND {tailored} AND {cover})",
        STAGE_TAILORED: f"({before_tailored} AND {tailored} AND {not_cover})",
        STAGE_TAILOR_EXHAUSTED: f"({before_tailor_exhausted} AND {tailor_exhausted})",
        STAGE_SCORED: f"({before_scored} AND {scored})",
        STAGE_ENRICHED: f"({before_enrich_error} AND {enriched})",
        STAGE_ENRICH_ERROR: f"({before_enrich_error} AND {enrich_error})",
        STAGE_DISCOVERED: f"({before_enrich_error} AND {not_enrich_error})",
    }
    clause = predicates.get(stage_label)
    if clause is None:
        case_sql = pipeline_stage_case_sql(
            max_apply_attempts=max_apply_attempts,
            max_tailor_attempts=max_tailor_attempts,
        )
        escaped = stage_label.replace("'", "''")
        return f"({case_sql}) = '{escaped}'"
    return clause
