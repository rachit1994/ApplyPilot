"""IP-reputation throttle — per-ATS-family / per-apex-domain daily submit caps.

The binding constraint on a single residential IP is reputation, not compute or
LLM cost (docs/maxed-apply-pipeline-jun-2026.md §2). This gate reads today's
*successful submits* from apply_outcomes and refuses to start another apply on a
family/domain that is already at its cap, so a big overnight run shapes itself
to a human-plausible volume instead of bursting one fingerprint.

Counting submits (not attempts) is deliberate: a job that escalated or failed
early didn't spend IP trust, so it shouldn't consume a slot.
"""

from __future__ import annotations

from datetime import datetime, timezone

from applypilot.apply import apply_settings
from applypilot.apply.direct import fingerprint
from applypilot.database import ensure_apply_outcomes_table, get_connection

# apply_outcomes.result values that represent a real form submission to the site.
_SUBMIT_RESULTS = (
    "applied",
    "submitted_unverified",
)


def _today_utc_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _submit_count(conn, *, ats_family: str | None, apex: str | None) -> int:
    ensure_apply_outcomes_table(conn)
    like = _today_utc_prefix() + "%"
    result_clause = " OR ".join("result LIKE ?" for _ in _SUBMIT_RESULTS)
    params: list = [f"{r}%" for r in _SUBMIT_RESULTS]
    where = f"created_at LIKE ? AND ({result_clause})"
    params.insert(0, like)
    if ats_family is not None:
        where += " AND ats_family = ?"
        params.append(ats_family)
    if apex is not None:
        where += " AND url LIKE ?"
        params.append(f"%{apex}%")
    row = conn.execute(
        f"SELECT COUNT(*) FROM apply_outcomes WHERE {where}", params
    ).fetchone()
    return int(row[0]) if row else 0


def check_caps(url: str, *, conn=None) -> tuple[bool, str | None]:
    """Return (allowed, reason). reason is a 'failed:*' deferral string when blocked."""
    if conn is None:
        conn = get_connection()
    family = fingerprint.ats_family(url)
    apex = fingerprint.apex_domain(url)

    family_cap = apply_settings.max_per_ats_family_per_day()
    if family_cap > 0 and family != fingerprint.UNKNOWN_FAMILY:
        if _submit_count(conn, ats_family=family, apex=None) >= family_cap:
            return False, f"failed:direct_family_cap:{family}"

    domain_cap = apply_settings.max_per_apex_domain_per_day()
    if domain_cap > 0 and apex:
        if _submit_count(conn, ats_family=None, apex=apex) >= domain_cap:
            return False, f"failed:direct_domain_cap:{apex}"

    return True, None
