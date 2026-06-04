"""Worker apply playbook prompt: load docs/worker-apply-playbook.md and substitute tokens."""

from __future__ import annotations

import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from applypilot import config
from applypilot.apply.prompt import ensure_resume_pdf
from applypilot.role_resumes import resolve_job_resume_path
from applypilot.apply.worker_playbook_tools import build_tool_alias_section

_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")


def default_playbook_path() -> Path:
    """Repo-relative path to the worker apply playbook markdown."""
    return Path(__file__).resolve().parents[3] / "docs" / "worker-apply-playbook.md"


def load_playbook_markdown(path: Path | None = None) -> str:
    playbook_path = path or default_playbook_path()
    if not playbook_path.is_file():
        raise FileNotFoundError(f"Worker apply playbook not found: {playbook_path}")
    return playbook_path.read_text(encoding="utf-8")


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def build_playbook_tokens(
    profile: dict,
    job: dict,
    *,
    resume_pdf_path: str,
    cover_letter_pdf_path: str = "",
    cover_letter_text: str = "",
) -> dict[str, str]:
    """Build {{token}} values from profile and job (no invented fields)."""
    personal = profile["personal"]
    work_auth = profile["work_authorization"]
    comp = profile["compensation"]
    exp = profile.get("experience", {})
    avail = profile.get("availability", {})

    full_name = str(personal.get("full_name") or "").strip()
    name_parts = full_name.split()
    preferred = str(personal.get("preferred_name") or "").strip()
    if not preferred and name_parts:
        preferred = name_parts[0]

    from applypilot.config import get_target_roles

    roles = get_target_roles(profile)
    current_title = str(exp.get("current_job_title") or "").strip()
    if not current_title and roles:
        current_title = roles[0]

    job_url = str(job.get("application_url") or job.get("url") or "").strip()
    eeo = profile.get("eeo_voluntary") or {}

    raw_phone = str(personal.get("phone") or "").strip()
    phone_digits = _digits_only(raw_phone)
    # E.164 (+countrycode...) when the stored number carries a country code, so
    # international phone widgets (intl-tel-input on Greenhouse, etc.) detect the
    # right country instead of treating it as an over-long US number.
    phone_e164 = ("+" + phone_digits) if raw_phone.startswith("+") else phone_digits

    return {
        "full_name": full_name,
        "preferred_name": preferred,
        "email": str(personal.get("email") or "").strip(),
        "phone": str(personal.get("phone") or "").strip(),
        "phone_digits": phone_digits,
        "phone_e164": phone_e164,
        "address": str(personal.get("address") or "").strip(),
        "city": str(personal.get("city") or "").strip(),
        "province_state": str(personal.get("province_state") or "").strip(),
        "country": str(personal.get("country") or "").strip(),
        "postal_code": str(personal.get("postal_code") or "").strip(),
        "linkedin_url": str(personal.get("linkedin_url") or "").strip(),
        "github_url": str(personal.get("github_url") or "").strip(),
        "portfolio_url": str(
            personal.get("portfolio_url") or personal.get("website_url") or ""
        ).strip(),
        "work_auth": str(work_auth.get("legally_authorized_to_work") or "").strip(),
        "require_sponsorship": str(work_auth.get("require_sponsorship") or "").strip(),
        "work_permit_type": str(work_auth.get("work_permit_type") or "").strip(),
        "salary_number": str(comp.get("salary_expectation") or "").strip(),
        "salary_currency": str(comp.get("salary_currency") or "USD").strip(),
        "years_experience": str(exp.get("years_of_experience_total") or "").strip(),
        "education_level": str(exp.get("education_level") or "").strip(),
        "current_job_title": current_title,
        "job_title": str(job.get("title") or "").strip(),
        "company": str(job.get("site") or job.get("company") or "").strip(),
        "earliest_start_date": str(avail.get("earliest_start_date") or "Immediately").strip(),
        # Concrete date (MM/DD/YYYY) for date-picker "when can you start" fields,
        # which reject free text like "Immediately". Two weeks out = realistic notice.
        "start_date": (date.today() + timedelta(days=14)).strftime("%m/%d/%Y"),
        "resume_pdf_path": resume_pdf_path,
        "cover_letter_pdf_path": cover_letter_pdf_path,
        "cover_letter_text": cover_letter_text.strip(),
        "today_date": date.today().isoformat(),
        "job_url": job_url,
        "password": str(personal.get("password") or "").strip(),
        "gender": str(eeo.get("gender") or "Decline to self-identify").strip(),
        "race_ethnicity": str(eeo.get("race_ethnicity") or "Decline to self-identify").strip(),
        "veteran_status": str(
            eeo.get("veteran_status") or "I am not a protected veteran"
        ).strip(),
        "disability_status": str(
            eeo.get("disability_status") or "I do not wish to answer"
        ).strip(),
    }


def render_worker_playbook_prompt(
    tokens: dict[str, str],
    *,
    playbook_body: str | None = None,
    playbook_path: Path | None = None,
    include_tool_aliases: bool = True,
) -> str:
    """Substitute {{tokens}} in playbook markdown and append tool aliases."""
    body = playbook_body if playbook_body is not None else load_playbook_markdown()
    token_source = playbook_path or default_playbook_path()

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in tokens:
            raise ValueError(f"Unknown playbook token {{{{{key}}}}} in {token_source}")
        return tokens[key]

    rendered = _TOKEN_RE.sub(_replace, body)
    if include_tool_aliases:
        alias_body = _TOKEN_RE.sub(_replace, build_tool_alias_section())
        rendered = rendered.rstrip() + "\n\n" + alias_body.lstrip()
    return rendered


def build_worker_apply_prompt(
    job: dict,
    *,
    upload_dir: Path | None = None,
    playbook_path: Path | None = None,
) -> str:
    """Build stdin prompt for playbook apply mode (resume copy + token substitution)."""
    profile = config.load_profile()
    personal = profile["personal"]

    resume_path = resolve_job_resume_path(job)
    if not resume_path:
        raise ValueError(f"No tailored resume for job: {job.get('title', 'unknown')}")

    src_pdf = ensure_resume_pdf(resume_path)
    full_name = personal["full_name"]
    name_slug = full_name.replace(" ", "_")
    dest_dir = upload_dir or (config.APPLY_WORKER_DIR / "current")
    dest_dir.mkdir(parents=True, exist_ok=True)
    upload_pdf = dest_dir / f"{name_slug}_Resume.pdf"
    shutil.copy(str(src_pdf), str(upload_pdf))
    pdf_path = str(upload_pdf)

    from applypilot.apply.cover_resolve import resolve_apply_cover_letter

    _cl_text, _cl_txt, cl_upload_path = resolve_apply_cover_letter(
        job, upload_dir=dest_dir
    )

    tokens = build_playbook_tokens(
        profile,
        job,
        resume_pdf_path=pdf_path,
        cover_letter_pdf_path=cl_upload_path,
        cover_letter_text=_cl_text,
    )
    resolved_path = playbook_path or default_playbook_path()
    body = load_playbook_markdown(resolved_path)
    return render_worker_playbook_prompt(
        tokens,
        playbook_body=body,
        playbook_path=resolved_path,
    )
