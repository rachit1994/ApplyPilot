"""Tailored resume + PDF preparation for referral outreach."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import RESUME_PATH, TAILORED_DIR, load_profile
from applypilot.database import get_connection
from applypilot.scoring.pdf import convert_to_pdf
from applypilot.scoring.tailor import tailor_resume

log = logging.getLogger(__name__)

_SUCCESS_STATUSES = frozenset({"approved", "approved_with_judge_warning"})


@dataclass(frozen=True)
class ResumeBundle:
    """Paths and excerpt for a job-specific resume used in referral drafting."""

    txt_path: Path | None
    pdf_path: Path | None
    excerpt: str


def company_from_job(job: dict) -> str | None:
    """Best-effort company name from job row."""
    site = (job.get("site") or "").strip()
    site_lower = site.lower()
    is_linkedin_board = site_lower in ("linkedin", "linkedin.com") or site_lower.startswith(
        "linkedin "
    )
    if site and not is_linkedin_board:
        return site.split("(")[0].strip() or None
    title = job.get("title") or ""
    if " at " in title:
        return title.rsplit(" at ", 1)[-1].strip()
    return None


def _prefix_for_job(job: dict) -> str:
    safe_title = re.sub(r"[^\w\s-]", "", job["title"])[:50].strip().replace(" ", "_")
    safe_site = re.sub(r"[^\w\s-]", "", job.get("site") or "")[:20].strip().replace(" ", "_")
    return f"{safe_site}_{safe_title}"


def _read_excerpt(path: Path, max_chars: int) -> str:
    text = path.read_text(encoding="utf-8")
    return text[:max_chars].strip()


def _ensure_pdf(txt_path: Path) -> Path | None:
    pdf_path = txt_path.with_suffix(".pdf")
    if pdf_path.exists():
        return pdf_path
    try:
        return convert_to_pdf(txt_path, pdf_path)
    except Exception:
        log.debug("PDF generation failed for %s", txt_path, exc_info=True)
        return None


def _persist_tailored(
    conn,
    job: dict,
    txt_path: Path,
    pdf_path: Path | None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
        "tailor_attempts=COALESCE(tailor_attempts,0)+1, referral_resume_path=? WHERE url=?",
        (str(txt_path), now, str(pdf_path) if pdf_path else None, job["url"]),
    )
    conn.commit()


def _tailor_and_save(job: dict, profile: dict, validation_mode: str) -> ResumeBundle:
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    tailored, report = tailor_resume(
        resume_text, job, profile, validation_mode=validation_mode
    )
    if report.get("status") not in _SUCCESS_STATUSES:
        raise RuntimeError(
            f"Tailoring failed for {job.get('title', job.get('url'))}: {report.get('status')}"
        )

    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    prefix = _prefix_for_job(job)
    txt_path = TAILORED_DIR / f"{prefix}.txt"
    txt_path.write_text(tailored, encoding="utf-8")

    job_path = TAILORED_DIR / f"{prefix}_JOB.txt"
    job_desc = (
        f"Title: {job['title']}\n"
        f"Company: {job.get('site')}\n"
        f"Location: {job.get('location', 'N/A')}\n"
        f"Score: {job.get('fit_score', 'N/A')}\n"
        f"URL: {job['url']}\n\n"
        f"{job.get('full_description', '')}"
    )
    job_path.write_text(job_desc, encoding="utf-8")
    report_path = TAILORED_DIR / f"{prefix}_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    pdf_path = _ensure_pdf(txt_path)
    conn = get_connection()
    _persist_tailored(conn, job, txt_path, pdf_path)
    return ResumeBundle(txt_path=txt_path, pdf_path=pdf_path, excerpt=tailored)


def ensure_job_resume(
    job: dict,
    *,
    validation_mode: str = "normal",
    excerpt_chars: int = 2500,
    force_retailor: bool = False,
) -> ResumeBundle:
    """Return tailored resume paths, tailoring + PDF if missing."""
    profile = load_profile()
    existing = (job.get("tailored_resume_path") or "").strip()
    txt_path: Path | None = None

    if existing and not force_retailor:
        candidate = Path(existing)
        if candidate.is_file():
            txt_path = candidate

    if txt_path is None:
        bundle = _tailor_and_save(job, profile, validation_mode)
        return ResumeBundle(
            txt_path=bundle.txt_path,
            pdf_path=bundle.pdf_path,
            excerpt=_read_excerpt(bundle.txt_path, excerpt_chars) if bundle.txt_path else "",
        )

    pdf_path = _ensure_pdf(txt_path)
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET referral_resume_path=? WHERE url=?",
        (str(pdf_path) if pdf_path else None, job["url"]),
    )
    conn.commit()
    return ResumeBundle(
        txt_path=txt_path,
        pdf_path=pdf_path,
        excerpt=_read_excerpt(txt_path, excerpt_chars),
    )
