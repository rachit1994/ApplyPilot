"""OpenOutreach connect and message orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from applypilot.database import get_connection
from applypilot.outreach.config import OutreachSettings, load_outreach_config
from applypilot.outreach.openoutreach_client import OpenOutreachClient, OpenOutreachError
from applypilot.outreach.referral_draft import finalize_referral_message
from applypilot.outreach.referral_resume import company_from_job

log = logging.getLogger(__name__)

CONNECTED_STATE = "Connected"
PENDING_STATE = "Pending"


def _client(settings: OutreachSettings) -> OpenOutreachClient:
    return OpenOutreachClient(settings.openoutreach_base_url, settings.openoutreach_api_key)


def _weekly_connects_used(conn) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE referral_connect_at >= datetime('now', '-7 days')
          AND referral_connect_at IS NOT NULL
        """
    ).fetchone()
    return int(row[0]) if row else 0


def _applied_clause(settings: OutreachSettings) -> str:
    if settings.require_applied_before_send:
        return "AND applied_at IS NOT NULL"
    if settings.skip_if_applied:
        return "AND applied_at IS NULL"
    return ""


def _url_filter(urls: list[str] | None, params: list) -> tuple[str, list]:
    if not urls:
        return "", params
    placeholders = ",".join("?" * len(urls))
    return f" AND url IN ({placeholders})", [*params, *urls]


def _eligible_connect_rows(
    conn,
    settings: OutreachSettings,
    *,
    urls: list[str] | None = None,
) -> list[dict]:
    applied_clause = _applied_clause(settings)
    query = f"""
        SELECT * FROM jobs
        WHERE fit_score >= ?
          AND recruiter_public_id IS NOT NULL
          AND recruiter_public_id != ''
          AND referral_message IS NOT NULL
          AND referral_message != ''
          AND (referral_status IS NULL OR referral_status = 'pending_connect')
          AND discovered_at >= datetime('now', ? || ' hours')
          {applied_clause}
        ORDER BY fit_score DESC, discovered_at DESC
    """
    params: list = [settings.min_fit_score, f"-{settings.max_job_age_hours}"]
    url_clause, params = _url_filter(urls, params)
    query = query.rstrip() + url_clause
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return []
    columns = rows[0].keys()
    return [dict(zip(columns, row)) for row in rows]


def _eligible_message_rows(
    conn,
    settings: OutreachSettings,
    *,
    urls: list[str] | None = None,
) -> list[dict]:
    applied_clause = _applied_clause(settings)
    query = f"""
        SELECT * FROM jobs
        WHERE referral_status = 'connect_sent'
          AND recruiter_public_id IS NOT NULL
          AND referral_message IS NOT NULL
          AND referral_message != ''
          {applied_clause}
        ORDER BY referral_connect_at ASC
    """
    params: list = []
    url_clause, params = _url_filter(urls, params)
    query = query.rstrip() + url_clause
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return []
    columns = rows[0].keys()
    return [dict(zip(columns, row)) for row in rows]


def _deal_state_by_public_id(client: OpenOutreachClient, settings: OutreachSettings) -> dict[str, str]:
    deals = client.list_deals(campaign=settings.openoutreach_campaign, limit=500)
    return {d["public_id"]: d.get("state", "") for d in deals if d.get("public_id")}


def run_referral_connect(
    *,
    settings: OutreachSettings | None = None,
    dry_run: bool = False,
    urls: list[str] | None = None,
) -> dict:
    settings = settings or load_outreach_config()
    conn = get_connection()
    jobs = _eligible_connect_rows(conn, settings, urls=urls)
    sent = 0
    failed = 0

    if dry_run:
        return {"connect_sent": 0, "candidates": len(jobs), "dry_run": True}

    weekly_used = _weekly_connects_used(conn)
    remaining_weekly = max(0, settings.weekly_connect_target - weekly_used)
    cap = min(settings.max_connects_per_run, remaining_weekly)
    if cap <= 0:
        return {"connect_sent": 0, "candidates": len(jobs), "stopped": "weekly_connect_target reached"}

    client = _client(settings)
    try:
        oo_status = client.status()
    except OpenOutreachError as exc:
        return {"connect_sent": 0, "error": str(exc)}

    if not oo_status.get("rate_limits", {}).get("can_connect", True):
        return {"connect_sent": 0, "stopped": "OpenOutreach connect rate limit"}

    for job in jobs[:cap]:
        public_id = job["recruiter_public_id"]
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = client.connect(public_id, campaign=settings.openoutreach_campaign, wait=True)
            deal_id = None
            if isinstance(result, dict):
                inner = result.get("result") or result
                if isinstance(inner, dict):
                    deal_id = inner.get("deal_id")
            conn.execute(
                """
                UPDATE jobs SET
                    referral_status = 'connect_sent',
                    referral_connect_at = ?,
                    referral_error = NULL,
                    referral_openoutreach_deal_id = COALESCE(?, referral_openoutreach_deal_id)
                WHERE url = ?
                """,
                (now, deal_id, job["url"]),
            )
            conn.commit()
            sent += 1
        except OpenOutreachError as exc:
            conn.execute(
                """
                UPDATE jobs SET referral_status = 'failed', referral_error = ? WHERE url = ?
                """,
                (str(exc), job["url"]),
            )
            conn.commit()
            failed += 1
            if exc.status_code in (401, 429):
                break

    return {"connect_sent": sent, "failed": failed, "candidates": len(jobs)}


def run_referral_message(
    *,
    settings: OutreachSettings | None = None,
    dry_run: bool = False,
    urls: list[str] | None = None,
) -> dict:
    settings = settings or load_outreach_config()
    conn = get_connection()
    jobs = _eligible_message_rows(conn, settings, urls=urls)
    sent = 0
    failed = 0

    if dry_run:
        return {"messages_sent": 0, "candidates": len(jobs), "dry_run": True}

    if not jobs:
        return {"messages_sent": 0, "candidates": 0}

    client = _client(settings)
    try:
        oo_status = client.status()
    except OpenOutreachError as exc:
        return {"messages_sent": 0, "error": str(exc)}

    if not oo_status.get("rate_limits", {}).get("can_follow_up", True):
        return {"messages_sent": 0, "stopped": "OpenOutreach message rate limit"}

    states = _deal_state_by_public_id(client, settings)
    cap = settings.max_messages_per_run

    for job in jobs:
        if sent >= cap:
            break
        public_id = job["recruiter_public_id"]
        state = states.get(public_id, "")
        if state == PENDING_STATE:
            continue
        if state != CONNECTED_STATE:
            continue

        now = datetime.now(timezone.utc).isoformat()
        if settings.require_gemini_for_draft:
            body = finalize_referral_message(
                job["referral_message"] or "",
                job_title=job.get("title") or "",
                company=company_from_job(job) or "",
            )
        else:
            body = (job["referral_message"] or "").strip()
        if not body:
            conn.execute(
                "UPDATE jobs SET referral_error = ? WHERE url = ?",
                ("empty referral message after finalize", job["url"]),
            )
            conn.commit()
            failed += 1
            continue
        try:
            client.message(
                public_id,
                body,
                campaign=settings.openoutreach_campaign,
                wait=True,
            )
            conn.execute(
                """
                UPDATE jobs SET
                    referral_status = 'message_sent',
                    referral_message_at = ?,
                    referral_error = NULL
                WHERE url = ?
                """,
                (now, job["url"]),
            )
            conn.commit()
            sent += 1
            resume_path = job.get("referral_resume_path")
            if resume_path:
                log.info(
                    "Referral message sent for %s — attach resume manually if needed: %s",
                    job.get("title", job["url"])[:50],
                    resume_path,
                )
        except OpenOutreachError as exc:
            if "URN" in str(exc) or exc.code == "message_failed":
                try:
                    client.scrape_profile(public_id, campaign=settings.openoutreach_campaign)
                    client.message(
                        public_id,
                        body,
                        campaign=settings.openoutreach_campaign,
                        wait=True,
                    )
                    conn.execute(
                        """
                        UPDATE jobs SET
                            referral_status = 'message_sent',
                            referral_message_at = ?,
                            referral_error = NULL
                        WHERE url = ?
                        """,
                        (now, job["url"]),
                    )
                    conn.commit()
                    sent += 1
                    continue
                except OpenOutreachError:
                    pass
            conn.execute(
                "UPDATE jobs SET referral_error = ? WHERE url = ?",
                (str(exc), job["url"]),
            )
            conn.commit()
            failed += 1
            if exc.status_code in (401, 429):
                break

    return {"messages_sent": sent, "failed": failed, "candidates": len(jobs)}
