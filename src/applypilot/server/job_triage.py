"""Jobs tab filter chips — one SQL predicate per slug for list + counts."""

from __future__ import annotations

from applypilot import config
from applypilot.db.connection import Connection
from applypilot.db.dialect import scalar
from applypilot.server.job_pipeline_stage import (
    STAGE_APPLIED,
    STAGE_APPLYING,
    STAGE_COVER,
    STAGE_DISCOVERED,
    STAGE_ENRICHED,
    STAGE_ENRICH_ERROR,
    STAGE_READY,
    STAGE_SCORED,
    STAGE_TAILORED,
    pipeline_stage_case_sql,
    stage_filter_clause,
)

# Slugs sent by dashboard Jobs filter chips (?stage=).
TRIAGE_SLUGS: frozenset[str] = frozenset(
    {"new", "tailored", "applied", "failed", "ready", "pending_score", "rejected"}
)

# Legacy / mistyped URLs still seen in bookmarks.
_TRIAGE_ALIASES: dict[str, str] = {
    "scored": "new",
    "submitted": "applied",
    "saved": "ready",
    "not_scored": "pending_score",
    "discovered": "pending_score",
}


def normalize_triage_slug(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    slug = str(raw).strip().lower()
    slug = _TRIAGE_ALIASES.get(slug, slug)
    return slug if slug in TRIAGE_SLUGS else None


def is_triage_slug(raw: str | None) -> bool:
    return normalize_triage_slug(raw) is not None


def _stage_in_labels(*labels: str) -> str:
    case_sql = pipeline_stage_case_sql()
    quoted = ", ".join(f"'{label}'" for label in labels)
    return f"({case_sql}) IN ({quoted})"


def triage_filter_clause(slug: str) -> str:
    """WHERE fragment (no leading WHERE) for a triage chip slug."""
    normalized = normalize_triage_slug(slug)
    if normalized is None:
        raise ValueError(f"unknown triage slug: {slug!r}")

    if normalized == "new":
        return (
            _stage_in_labels(
                STAGE_DISCOVERED,
                STAGE_ENRICHED,
                STAGE_ENRICH_ERROR,
                STAGE_SCORED,
                STAGE_APPLYING,
            )
            + " AND pre_filter_rejected_at IS NULL AND pre_filter_reason IS NULL"
        )
    if normalized == "tailored":
        return _stage_in_labels(STAGE_TAILORED, STAGE_COVER, STAGE_READY)
    if normalized == "applied":
        return stage_filter_clause(STAGE_APPLIED)
    if normalized == "failed":
        return (
            "((apply_error IS NOT NULL AND TRIM(apply_error) != '') "
            "OR apply_status = 'failed')"
        )
    if normalized == "rejected":
        return "(pre_filter_rejected_at IS NOT NULL OR pre_filter_reason IS NOT NULL)"
    if normalized == "ready":
        max_apply = int(config.DEFAULTS["max_apply_attempts"])
        return stage_filter_clause(STAGE_READY, max_apply_attempts=max_apply)
    if normalized == "pending_score":
        return (
            "(fit_score IS NULL "
            "AND (apply_status IS NULL OR apply_status != 'applied'))"
        )
    raise ValueError(f"unhandled triage slug: {normalized!r}")


def count_for_triage(conn: Connection, slug: str) -> int:
    """Count jobs matching the same predicate as query_jobs for this triage slug."""
    normalized = normalize_triage_slug(slug)
    if normalized is None:
        return 0
    clause = triage_filter_clause(normalized)
    row = conn.execute(f"SELECT COUNT(*) AS c FROM jobs WHERE {clause}").fetchone()
    return int(scalar(row) or 0)


def fetch_triage_counts(conn: Connection | None = None) -> dict[str, int]:
    """Counts keyed by triage slug; must stay in sync with triage_filter_clause."""
    from applypilot.database import get_connection

    if conn is None:
        conn = get_connection()
    return {slug: count_for_triage(conn, slug) for slug in sorted(TRIAGE_SLUGS)}
