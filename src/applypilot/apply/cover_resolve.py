"""Resolve cover letter text/PDF for apply using the same resume as :func:`resolve_job_resume`."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from applypilot import config
from applypilot.config import load_profile
from applypilot.role_resumes import resolve_job_resume, resolve_job_resume_text
from applypilot.scoring.cover_letter import generate_cover_letter_with_routing
from applypilot.scoring.pdf import convert_to_pdf


def _job_file_prefix(job: dict) -> str:
    safe_title = re.sub(r"[^\w\s-]", "", str(job.get("title") or ""))[:50].strip().replace(" ", "_")
    safe_site = re.sub(r"[^\w\s-]", "", str(job.get("site") or ""))[:20].strip().replace(" ", "_")
    return f"{safe_site}_{safe_title}" if safe_site or safe_title else "job"


def _read_cover_text(path: Path) -> str:
    if path.suffix == ".txt" and path.is_file():
        return path.read_text(encoding="utf-8")
    sibling = path.with_suffix(".txt")
    if sibling.is_file():
        return sibling.read_text(encoding="utf-8")
    return ""


def _cover_aligned_with_resolution(
    cl_path: str,
    resolution,
    job: dict | None = None,
) -> bool:
    """True when a stored cover letter matches the resume we will apply with."""
    if resolution.role_key:
        slug = resolution.role_key.replace("-", "").lower()
        name = Path(cl_path).name.lower().replace("-", "")
        return bool(slug and slug in name)
    if resolution.source == "tailored" and job:
        prefix = _job_file_prefix(job).lower().replace("_", "")
        name = Path(cl_path).name.lower().replace("_", "").replace("-", "")
        return bool(prefix and prefix in name)
    return resolution.source == "base"


def _role_cover_cache_txt(job: dict, role_key: str) -> Path:
    return config.COVER_LETTER_DIR / f"role_{role_key}_{_job_file_prefix(job)}_CL.txt"


def _copy_cover_pdf_for_upload(
    cl_src: Path,
    dest_dir: Path,
    name_slug: str,
) -> str:
    cl_pdf_src = cl_src.with_suffix(".pdf")
    if not cl_pdf_src.is_file():
        try:
            convert_to_pdf(cl_src)
        except Exception:  # noqa: BLE001
            return ""
        cl_pdf_src = cl_src.with_suffix(".pdf")
    if not cl_pdf_src.is_file():
        return ""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cl_upload = dest_dir / f"{name_slug}_Cover_Letter.pdf"
    shutil.copy(str(cl_pdf_src), str(cl_upload))
    return str(cl_upload)


def resolve_apply_cover_letter(
    job: dict,
    *,
    upload_dir: Path | None = None,
) -> tuple[str, str, str]:
    """Return ``(plain_text, txt_path, pdf_upload_path)`` for the apply agent.

    Regenerates or uses a role-keyed cache when the job's DB cover letter was
    built for a different resume than :func:`resolve_job_resume` selects now.
    """
    resolution = resolve_job_resume(job)
    profile = load_profile()
    personal = profile["personal"]
    name_slug = str(personal.get("full_name", "Applicant")).replace(" ", "_")
    dest_dir = upload_dir or (config.APPLY_WORKER_DIR / "current")

    cl_path = job.get("cover_letter_path")
    if cl_path and Path(cl_path).exists() and _cover_aligned_with_resolution(
        str(cl_path), resolution, job
    ):
        src = Path(cl_path)
        text = _read_cover_text(src)
        pdf_upload = _copy_cover_pdf_for_upload(src, dest_dir, name_slug)
        return text, str(src.with_suffix(".txt") if src.suffix != ".txt" else src), pdf_upload

    if resolution.role_key:
        cached = _role_cover_cache_txt(job, resolution.role_key)
        if cached.is_file():
            text = cached.read_text(encoding="utf-8")
            pdf_upload = _copy_cover_pdf_for_upload(cached, dest_dir, name_slug)
            return text, str(cached), pdf_upload

    resume_text = resolve_job_resume_text(job) or config.RESUME_PATH.read_text(encoding="utf-8")
    letter, _report = generate_cover_letter_with_routing(resume_text, job, profile)

    config.COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    if resolution.role_key:
        out_txt = _role_cover_cache_txt(job, resolution.role_key)
    else:
        out_txt = config.COVER_LETTER_DIR / f"{_job_file_prefix(job)}_CL.txt"
    out_txt.write_text(letter, encoding="utf-8")
    pdf_upload = _copy_cover_pdf_for_upload(out_txt, dest_dir, name_slug)
    return letter, str(out_txt), pdf_upload
