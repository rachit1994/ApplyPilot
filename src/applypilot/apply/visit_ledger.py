"""Track canonical apply URLs visited and block tight re-apply loops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from applypilot.apply import apply_settings
from applypilot.apply.apply_url_extract import coerce_application_url
from applypilot.database import ensure_apply_outcomes_table, get_connection

_SUCCESS_RESULTS = frozenset({"applied", "submitted_unverified"})


def canonical_apply_url(url: str | None) -> str:
    """Normalize an apply URL for dedup lookups (host + path, no query)."""
    raw = coerce_application_url(url) or str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").rstrip("/") or "/"
    return f"{host}{path}"


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes_since(created_at: str | None, *, now: datetime | None = None) -> float | None:
    created = _parse_created_at(created_at)
    if created is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() / 60.0


def _is_success_result(result: str | None) -> bool:
    text = str(result or "").strip()
    if not text:
        return False
    if text in _SUCCESS_RESULTS:
        return True
    return text.startswith("applied")


def latest_apply_visit(apply_url: str, *, conn=None) -> dict | None:
    """Return the most recent apply_outcomes row for this canonical apply URL."""
    canon = canonical_apply_url(apply_url)
    if not canon:
        return None
    if conn is None:
        conn = get_connection()
    ensure_apply_outcomes_table(conn)
    row = conn.execute(
        """
        SELECT url, ats_family, fingerprint, result, tier_resolved,
               escalated, escalate_reason, fields_total, fields_llm,
               elapsed_ms, created_at, canonical_url
        FROM apply_outcomes
        WHERE canonical_url = ?
           OR lower(rtrim(url, '/')) = ?
        ORDER BY created_at::timestamptz DESC
        LIMIT 1
        """,
        (canon, canon),
    ).fetchone()
    return dict(row) if row else None


def _is_dry_run_result(result: str | None) -> bool:
    return "dry_run" in str(result or "").lower()


def visit_should_skip(
    apply_url: str,
    *,
    force: bool = False,
    conn=None,
) -> tuple[bool, str | None, dict | None]:
    """Return (skip, reason, last_visit) when this apply URL should not be opened again."""
    if force or not apply_url:
        return False, None, None
    visit = latest_apply_visit(apply_url, conn=conn)
    if not visit:
        return False, None, None
    result = str(visit.get("result") or "")
    if _is_dry_run_result(result):
        return False, None, visit
    if _is_success_result(result):
        return True, f"already_applied:{result}", visit
    minutes = _minutes_since(visit.get("created_at"))
    repeat_min = apply_settings.apply_visit_repeat_minutes()
    if minutes is not None and minutes < repeat_min:
        return True, f"recent_visit:{result}", visit
    return False, None, visit


def persist_visit_skip(
    job_url: str,
    block_reason: str,
    *,
    conn=None,
) -> None:
    """Set apply_not_before so acquire_job stops tight-looping on this job row."""
    if conn is None:
        conn = get_connection()
    repeat_min = apply_settings.apply_visit_repeat_minutes()
    not_before = (
        datetime.now(timezone.utc) + timedelta(minutes=repeat_min)
    ).isoformat()
    detail = f"apply_visit:{(block_reason or 'blocked')[:160]}"
    row = conn.execute(
        "SELECT apply_status FROM jobs WHERE url = ?",
        (job_url,),
    ).fetchone()
    status = str(row["apply_status"] or "") if row else ""
    if status in ("needs_adapter", "manual", "awaiting_login"):
        new_status = status
    elif status == "in_progress" or not status:
        new_status = "failed"
    else:
        new_status = status
    conn.execute(
        """
        UPDATE jobs
        SET apply_not_before = ?,
            apply_error = ?,
            agent_id = NULL,
            apply_status = ?
        WHERE url = ?
        """,
        (not_before, detail, new_status, job_url),
    )
    conn.commit()
