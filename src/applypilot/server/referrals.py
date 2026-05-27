"""Referrals dashboard API — list queued outreach and run manual actions."""

from __future__ import annotations

from typing import Any

from applypilot.database import get_connection, init_db
from applypilot.outreach.config import load_outreach_config, outreach_is_configured
from applypilot.outreach.openoutreach_client import check_openoutreach_health
from applypilot.outreach.orchestrator import (
    _eligible_connect_rows,
    _eligible_message_rows,
    run_referral_connect,
    run_referral_message,
)
from applypilot.outreach.recruiter_scrape import _eligible_scrape_rows, run_recruiter_scrape
from applypilot.outreach.referral_draft import _eligible_draft_rows, run_referral_draft
from applypilot.outreach.referral_resume import company_from_job

MAX_ACTION_URLS = 25

_FILTER_SQL: dict[str, str] = {
    "all": "1=1",
    "needs_scrape": (
        "(recruiter_public_id IS NULL OR recruiter_public_id = '') "
        "AND (referral_status IS NULL OR referral_status = '')"
    ),
    "needs_message": (
        "recruiter_public_id IS NOT NULL AND recruiter_public_id != '' "
        "AND (referral_message IS NULL OR referral_message = '')"
    ),
    "ready_to_connect": (
        "recruiter_public_id IS NOT NULL AND referral_message IS NOT NULL "
        "AND referral_message != '' "
        "AND (referral_status IS NULL OR referral_status = 'pending_connect')"
    ),
    "awaiting_accept": "referral_status = 'connect_sent'",
    "ready_to_message": "referral_status = 'connect_sent'",
    "failed": "referral_status = 'failed'",
}


def _openoutreach_health(settings) -> dict[str, Any]:
    if not outreach_is_configured(settings):
        return {"reachable": False, "detail": "OpenOutreach not configured"}
    ok, detail = check_openoutreach_health(
        settings.openoutreach_base_url,
        settings.openoutreach_api_key,
    )
    return {"reachable": ok, "detail": detail}


def _row_flags(job: dict, settings, conn) -> dict[str, bool]:
    url = job["url"]
    scrape_eligible = any(r["url"] == url for r in _eligible_scrape_rows(conn, settings))
    draft_eligible = any(r["url"] == url for r in _eligible_draft_rows(conn, settings))
    connect_eligible = any(r["url"] == url for r in _eligible_connect_rows(conn, settings))
    message_eligible = any(r["url"] == url for r in _eligible_message_rows(conn, settings))
    return {
        "can_scrape": scrape_eligible,
        "can_template": draft_eligible,
        "can_connect": connect_eligible,
        "can_message": message_eligible,
    }


def query_referrals(
    *,
    filter_name: str = "all",
    search: str | None = None,
    min_score: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    init_db()
    settings = load_outreach_config()
    conn = get_connection()
    health = _openoutreach_health(settings)

    if not settings.enabled:
        return [], 0, {"outreach_enabled": False, "openoutreach": health}

    filt = _FILTER_SQL.get(filter_name, _FILTER_SQL["all"])
    min_fit = min_score if min_score is not None else settings.min_fit_score
    where_parts = [
        "fit_score >= ?",
        "discovered_at >= datetime('now', ? || ' hours')",
        filt,
    ]
    params: list[Any] = [min_fit, f"-{settings.max_job_age_hours}"]

    if search and search.strip():
        q = f"%{search.strip()}%"
        where_parts.append(
            "(title LIKE ? OR url LIKE ? OR recruiter_name LIKE ? OR recruiter_public_id LIKE ?)"
        )
        params.extend([q, q, q, q])

    where = " AND ".join(where_parts)
    total = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT url, title, site, location, fit_score, discovered_at,
               recruiter_name, recruiter_public_id, recruiter_scrape_error,
               referral_message, referral_status, referral_error,
               applied_at, referral_resume_path, referral_connect_at, referral_message_at,
               tailored_resume_path, score_reasoning
        FROM jobs
        WHERE {where}
        ORDER BY datetime(COALESCE(referral_message_at, referral_connect_at, applied_at, discovered_at)) DESC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        job = dict(row)
        job["company"] = company_from_job(job)
        job.update(_row_flags(job, settings, conn))
        items.append(job)

    meta = {
        "outreach_enabled": True,
        "openoutreach": health,
        "require_applied_before_send": settings.require_applied_before_send,
    }
    return items, int(total), meta


def run_referral_actions(action: str, urls: list[str]) -> dict[str, Any]:
    if action not in ("scrape", "draft", "connect", "message"):
        raise ValueError(f"Unknown action: {action}")
    if len(urls) > MAX_ACTION_URLS:
        raise ValueError(f"At most {MAX_ACTION_URLS} URLs per request")

    settings = load_outreach_config()
    if not settings.enabled:
        return {
            "action": action,
            "results": [{"url": u, "ok": False, "error": "outreach disabled"} for u in urls],
            "summary": {"ok": 0, "failed": len(urls)},
        }

    results: list[dict[str, Any]] = []
    ok_count = 0

    if action == "scrape":
        stage = run_recruiter_scrape(
            settings=settings, dry_run=False, headless=True, urls=urls
        )
        conn = get_connection()
        for url in urls:
            row = conn.execute(
                "SELECT recruiter_public_id, recruiter_scrape_error FROM jobs WHERE url = ?",
                (url,),
            ).fetchone()
            if row and row["recruiter_public_id"]:
                results.append({"url": url, "ok": True})
                ok_count += 1
            else:
                err = (row["recruiter_scrape_error"] if row else None) or "scrape failed"
                results.append({"url": url, "ok": False, "error": err})
        return {
            "action": action,
            "results": results,
            "summary": {"ok": ok_count, "failed": len(urls) - ok_count, "stage": stage},
        }

    if action == "draft":
        stage = run_referral_draft(settings=settings, dry_run=False, urls=urls)
        conn = get_connection()
        for url in urls:
            row = conn.execute(
                "SELECT referral_message FROM jobs WHERE url = ?", (url,)
            ).fetchone()
            if row and (row["referral_message"] or "").strip():
                results.append({"url": url, "ok": True})
                ok_count += 1
            else:
                results.append({"url": url, "ok": False, "error": "template not filled"})
        return {
            "action": action,
            "results": results,
            "summary": {"ok": ok_count, "failed": len(urls) - ok_count, "stage": stage},
        }

    if not outreach_is_configured(settings):
        err = "openoutreach_not_configured"
        return {
            "action": action,
            "results": [{"url": u, "ok": False, "error": err} for u in urls],
            "summary": {"ok": 0, "failed": len(urls)},
        }

    conn = get_connection()
    if action == "connect":
        eligible = {r["url"] for r in _eligible_connect_rows(conn, settings, urls=urls)}
    else:
        eligible = {r["url"] for r in _eligible_message_rows(conn, settings, urls=urls)}

    ineligible = [u for u in urls if u not in eligible]
    eligible_urls = [u for u in urls if u in eligible]

    for url in ineligible:
        reason = "not eligible"
        if settings.require_applied_before_send:
            row = conn.execute(
                "SELECT applied_at FROM jobs WHERE url = ?", (url,)
            ).fetchone()
            if row and not row["applied_at"]:
                reason = "not applied"
        results.append({"url": url, "ok": False, "error": reason})

    if eligible_urls:
        if action == "connect":
            stage = run_referral_connect(settings=settings, urls=eligible_urls)
        else:
            stage = run_referral_message(settings=settings, urls=eligible_urls)
        if stage.get("error"):
            for url in eligible_urls:
                results.append({"url": url, "ok": False, "error": stage["error"]})
        else:
            for url in eligible_urls:
                row = conn.execute(
                    "SELECT referral_status, referral_error FROM jobs WHERE url = ?",
                    (url,),
                ).fetchone()
                if action == "connect" and row and row["referral_status"] == "connect_sent":
                    results.append({"url": url, "ok": True})
                    ok_count += 1
                elif action == "message" and row and row["referral_status"] == "message_sent":
                    results.append({"url": url, "ok": True})
                    ok_count += 1
                else:
                    err = (row["referral_error"] if row else None) or f"{action} did not complete"
                    results.append({"url": url, "ok": False, "error": err})

    failed = len(urls) - ok_count
    return {
        "action": action,
        "results": results,
        "summary": {"ok": ok_count, "failed": failed},
    }
