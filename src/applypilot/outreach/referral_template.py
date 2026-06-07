"""Template-based referral messages (no LLM)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from applypilot.config import load_profile
from applypilot.database import get_connection
from applypilot.db.dialect import sql_discovered_hours_param
from applypilot.outreach.config import OutreachSettings, load_outreach_config
from applypilot.outreach.referral_resume import company_from_job

log = logging.getLogger(__name__)

_DEFAULT_TEMPLATE = (
    "Hi {recruiter_name}, I'm a Senior Engineering Leader (React/Node/Python/AWS) "
    "targeting the {job_title} role. I bring 10+ years of experience scaling "
    "distributed architectures and production RAG/multi-agent AI systems for 50M+ "
    "users. I'd love to connect and see if my background aligns with your team's needs!"
)

_PLACEHOLDER_PATTERN = re.compile(r"\[(Name|Job Title)\]", re.IGNORECASE)


def _normalize_template(text: str) -> str:
    """Map [Name] / [Job Title] to {recruiter_name} / {job_title}."""
    def _repl(match: re.Match[str]) -> str:
        key = match.group(1).lower().replace(" ", "_")
        if key == "name":
            return "{recruiter_name}"
        return "{job_title}"

    return _PLACEHOLDER_PATTERN.sub(_repl, text)


def render_referral_message(
    job: dict,
    *,
    settings: OutreachSettings | None = None,
    profile: dict | None = None,
) -> str:
    """Fill outreach template for one job row."""
    settings = settings or load_outreach_config()
    profile = profile or load_profile()
    template = _normalize_template(
        (settings.referral_message_template or "").strip() or _DEFAULT_TEMPLATE
    )
    personal = profile.get("personal", {})
    sender = (
        personal.get("preferred_name")
        or personal.get("full_name")
        or "me"
    )
    recruiter = (job.get("recruiter_name") or "").strip() or "there"
    title = (job.get("title") or "this role").strip()
    company = (company_from_job(job) or "your company").strip()
    try:
        return template.format(
            recruiter_name=recruiter,
            job_title=title,
            company=company,
            sender_name=sender,
        )
    except KeyError as exc:
        raise ValueError(f"Unknown placeholder in referral_message_template: {exc}") from exc


def _eligible_queue_rows(
    conn,
    settings: OutreachSettings,
    *,
    urls: list[str] | None = None,
) -> list[dict]:
    query = f"""
        SELECT * FROM jobs
        WHERE fit_score >= ?
          AND recruiter_public_id IS NOT NULL
          AND recruiter_public_id != ''
          AND (referral_message IS NULL OR referral_message = '')
          AND (referral_status IS NULL OR referral_status = '' OR referral_status = 'pending_connect')
          AND {sql_discovered_hours_param("discovered_at")}
    """
    params: list = [settings.min_fit_score, f"-{settings.max_job_age_hours}"]
    if urls:
        placeholders = ",".join("?" * len(urls))
        query += f" AND url IN ({placeholders})"
        params.extend(urls)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return []
    columns = rows[0].keys()
    return [dict(row) for row in rows]


def _resume_path_for_job(job: dict) -> str | None:
    existing = (job.get("tailored_resume_path") or "").strip()
    if not existing:
        return None
    p = Path(existing)
    if p.suffix == ".txt":
        pdf = p.with_suffix(".pdf")
        if pdf.is_file():
            return str(pdf)
        return str(p) if p.is_file() else None
    return str(p) if p.is_file() else None


def run_referral_queue(
    *,
    settings: OutreachSettings | None = None,
    limit: int = 50,
    dry_run: bool = False,
    urls: list[str] | None = None,
) -> dict:
    """Render template messages into referral_message for eligible jobs."""
    settings = settings or load_outreach_config()
    conn = get_connection()
    jobs = _eligible_queue_rows(conn, settings, urls=urls)[:limit]
    queued = 0

    if dry_run:
        return {"queued": 0, "candidates": len(jobs), "dry_run": True}

    for job in jobs:
        try:
            message = render_referral_message(job, settings=settings)
        except Exception as exc:
            log.error("Referral template failed for %s: %s", job.get("url"), exc)
            conn.execute(
                "UPDATE jobs SET referral_error = ?, referral_status = 'failed' WHERE url = ?",
                (str(exc), job["url"]),
            )
            conn.commit()
            continue

        resume_path = _resume_path_for_job(job)
        conn.execute(
            """
            UPDATE jobs SET
                referral_message = ?,
                referral_resume_path = COALESCE(?, referral_resume_path),
                referral_status = COALESCE(referral_status, 'pending_connect'),
                referral_error = NULL
            WHERE url = ?
            """,
            (message, resume_path, job["url"]),
        )
        conn.commit()
        queued += 1

    return {"queued": queued, "candidates": len(jobs)}
