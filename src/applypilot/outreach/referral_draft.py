"""Generate personalized referral request messages via Gemini."""

from __future__ import annotations

import logging
from pathlib import Path

from applypilot.config import load_profile
from applypilot.database import get_connection
from applypilot.db.dialect import sql_discovered_hours_param
from applypilot.llm import get_client, get_gemini_client
from applypilot.outreach.config import OutreachSettings, load_outreach_config
from applypilot.outreach.referral_resume import company_from_job, ensure_job_resume

log = logging.getLogger(__name__)

_BANNED_OPENERS = (
    "i hope this finds you well",
    "i hope you're doing well",
    "hope you are well",
    "pick your brain",
    "reach out",
    "touching base",
    "just wanted to reach out",
)
_ATTACH_MARKERS = ("attached", "attach", "enclosed", "including my resume")


def _build_referral_prompt(profile: dict, *, max_words: int) -> str:
    personal = profile.get("personal", {})
    name = personal.get("preferred_name") or personal.get("full_name", "the candidate")
    return f"""You write direct LinkedIn notes to recruiters after applying to a role.

Write as {name} in first person. At most {max_words} words. No hashtags. No emojis.

Structure (4 short sentences max):
1. "I applied for the [exact job title] role at [company]." — use the real title and company given.
2. One proof point from the resume excerpt (metric or outcome, one line).
3. Must include this idea verbatim in substance: a custom-made resume tailored for this role is attached with this note.
4. Direct ask: would you refer me or point me to the hiring manager?

Style: blunt and specific. No filler, no pleasantries, no "I hope this finds you well", no "pick your brain", no "I'd love to connect".
Return only the message body."""


def finalize_referral_message(
    message: str,
    *,
    job_title: str,
    company: str,
) -> str:
    """Ensure the note is direct and states a custom-made resume is attached."""
    text = " ".join(message.split()).strip()
    if not text:
        return text

    lower = text.lower()
    for phrase in _BANNED_OPENERS:
        if phrase in lower:
            idx = lower.find(phrase)
            text = (text[:idx] + text[idx + len(phrase) :]).strip()
            lower = text.lower()

    title = (job_title or "this role").strip()
    company_name = (company or "your company").strip()

    if title.lower() not in lower:
        text = f"I applied for the {title} role at {company_name}. {text}"

    lower = text.lower()
    has_attach = any(marker in lower for marker in _ATTACH_MARKERS)
    has_custom_resume = "custom-made resume" in lower or (
        "custom" in lower and "resume" in lower and ("tailored" in lower or "made" in lower)
    )
    if not (has_attach and has_custom_resume):
        text = (
            f"{text.rstrip()} I've attached a custom-made resume tailored for the "
            f"{title} role at {company_name}."
        )

    return text.strip()


def _draft_for_job(
    client,
    profile: dict,
    job: dict,
    *,
    resume_excerpt: str,
    pdf_attached: bool,
    max_words: int,
) -> str:
    system = _build_referral_prompt(profile, max_words=max_words)
    title = job.get("title") or "the role"
    company = company_from_job(job) or "the company"
    reasoning = (job.get("score_reasoning") or "")[:800]
    attach_line = (
        "A custom-made PDF resume for this role is ready — the note MUST say it is attached."
        if pdf_attached
        else "A custom-made resume for this role is ready — the note MUST say it is attached."
    )
    user = (
        f"Job title: {title}\n"
        f"Company: {company}\n"
        f"Location: {job.get('location') or 'n/a'}\n"
        f"Job URL: {job.get('url')}\n"
        f"Why I'm a fit (from scorer): {reasoning}\n\n"
        f"{attach_line}\n\n"
        f"Tailored resume excerpt (use for one achievement line only):\n{resume_excerpt}\n"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = client.chat(
        messages,
        temperature=0.35,
        max_tokens=500,
        operation="referral_draft",
    ).strip()
    return finalize_referral_message(raw, job_title=title, company=company)


def _eligible_draft_rows(
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
          AND (referral_status IS NULL OR referral_status = 'pending_connect')
          AND {sql_discovered_hours_param("discovered_at")}
    """
    age_param = f"-{settings.max_job_age_hours}"
    params: list = [settings.min_fit_score, age_param]
    if urls:
        placeholders = ",".join("?" * len(urls))
        query += f" AND url IN ({placeholders})"
        params.extend(urls)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return []
    columns = rows[0].keys()
    return [dict(row) for row in rows]


def _llm_client_for_referral(settings: OutreachSettings):
    if settings.require_gemini_for_draft:
        return get_gemini_client()
    return get_client()


def run_referral_draft(
    *,
    settings: OutreachSettings | None = None,
    limit: int = 50,
    dry_run: bool = False,
    urls: list[str] | None = None,
) -> dict:
    settings = settings or load_outreach_config()
    if not settings.require_gemini_for_draft:
        from applypilot.outreach.referral_template import run_referral_queue

        result = run_referral_queue(
            settings=settings,
            limit=limit,
            dry_run=dry_run,
            urls=urls,
        )
        return {
            "drafted": result.get("queued", 0),
            "candidates": result.get("candidates", 0),
            "resumes_built": 0,
            "dry_run": result.get("dry_run", False),
        }

    conn = get_connection()
    profile = load_profile()
    jobs = _eligible_draft_rows(conn, settings, urls=urls)[:limit]
    drafted = 0
    resumes_built = 0

    if dry_run:
        return {
            "drafted": 0,
            "candidates": len(jobs),
            "resumes_built": 0,
            "dry_run": True,
        }

    client = _llm_client_for_referral(settings)
    for job in jobs:
        resume_path: str | None = None
        try:
            if settings.ensure_tailored_resume:
                bundle = ensure_job_resume(
                    job,
                    validation_mode=settings.tailor_validation_mode,
                    excerpt_chars=settings.resume_excerpt_chars,
                )
                resumes_built += 1
                resume_excerpt = bundle.excerpt
                pdf_attached = bundle.pdf_path is not None
                resume_path = str(bundle.pdf_path or bundle.txt_path)
                job = dict(job)
                if bundle.txt_path:
                    job["tailored_resume_path"] = str(bundle.txt_path)
            else:
                resume_excerpt = ""
                pdf_attached = False
                existing = (job.get("tailored_resume_path") or "").strip()
                if existing:
                    p = Path(existing)
                    if p.is_file():
                        resume_excerpt = p.read_text(encoding="utf-8")[
                            : settings.resume_excerpt_chars
                        ]
                        resume_path = str(p.with_suffix(".pdf") if p.suffix == ".txt" else p)

            message = _draft_for_job(
                client,
                profile,
                job,
                resume_excerpt=resume_excerpt,
                pdf_attached=pdf_attached,
                max_words=settings.referral_message_max_words,
            )
        except Exception as exc:
            log.error("Referral draft failed for %s: %s", job.get("url"), exc)
            conn.execute(
                "UPDATE jobs SET referral_error = ?, referral_status = 'failed' WHERE url = ?",
                (str(exc), job["url"]),
            )
            conn.commit()
            continue

        conn.execute(
            "UPDATE jobs SET referral_message = ?, referral_resume_path = ? WHERE url = ?",
            (message, resume_path, job["url"]),
        )
        conn.commit()
        drafted += 1

    return {
        "drafted": drafted,
        "candidates": len(jobs),
        "resumes_built": resumes_built,
    }
