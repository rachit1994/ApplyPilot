"""Cover letter resolution stays aligned with resolve_job_resume at apply time."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_match_role_resume_returns_none_without_title_signal(tmp_path: Path):
    from applypilot import role_resumes

    pdf = tmp_path / "senior-full-stack-engineer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "senior-full-stack-engineer",
                        "title": "Senior Full Stack Engineer",
                        "aliases": ["software engineer"],
                        "keywords": ["python", "api"],
                        "pdf_path": str(pdf),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    match = role_resumes.match_role_resume(
        {
            "title": "Tax Accountant",
            "full_description": "Prepare corporate tax filings and audits.",
        },
        output_dir=tmp_path,
    )

    assert match is None


def test_resolve_apply_cover_letter_regenerates_when_role_resume_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from applypilot import config
    from applypilot.apply import cover_resolve

    ap_dir = tmp_path / "ap"
    ap_dir.mkdir()
    monkeypatch.setenv("APPLYPILOT_DIR", str(ap_dir))
    monkeypatch.setattr(config, "APP_DIR", ap_dir)
    monkeypatch.setattr(config, "PROFILE_PATH", ap_dir / "profile.json")
    monkeypatch.setattr(config, "COVER_LETTER_DIR", ap_dir / "cover_letters")
    (ap_dir / "cover_letters").mkdir(parents=True, exist_ok=True)
    (ap_dir / "resume.txt").write_text("Base resume", encoding="utf-8")
    (ap_dir / "profile.json").write_text(
        json.dumps(
            {
                "personal": {
                    "full_name": "Test User",
                    "email": "test@example.com",
                    "phone": "+15551234567",
                    "city": "Remote",
                },
                "work_authorization": {},
                "compensation": {},
            }
        ),
        encoding="utf-8",
    )

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "ai-engineer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "ai-engineer.txt"
    txt.write_text("LLM RAG LangChain production AI systems", encoding="utf-8")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "ai-engineer",
                        "title": "AI Engineer",
                        "aliases": ["ai engineer", "ml engineer"],
                        "keywords": ["llm", "rag"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", role_dir)

    stale_cl = ap_dir / "cover_letters" / "Acme_Software_Engineer_CL.txt"
    stale_cl.write_text("Generic cover for full-stack role.", encoding="utf-8")

    job = {
        "title": "Senior AI Engineer",
        "site": "Acme",
        "full_description": "Build LLM and RAG systems in production.",
        "cover_letter_path": str(stale_cl),
    }

    with patch(
        "applypilot.apply.cover_resolve.generate_cover_letter_with_routing",
        return_value=("AI-specific cover letter body.", {"source": "llm"}),
    ) as gen:
        text, txt_path, pdf_upload = cover_resolve.resolve_apply_cover_letter(job)

    gen.assert_called_once()
    assert "AI-specific" in text
    assert "role_ai-engineer" in txt_path
    assert Path(txt_path).is_file()


def test_resolve_apply_cover_letter_rejects_misaligned_tailored_cover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from applypilot import config
    from applypilot.apply import cover_resolve

    ap_dir = tmp_path / "ap"
    ap_dir.mkdir()
    monkeypatch.setenv("APPLYPILOT_DIR", str(ap_dir))
    monkeypatch.setattr(config, "APP_DIR", ap_dir)
    monkeypatch.setattr(config, "PROFILE_PATH", ap_dir / "profile.json")
    monkeypatch.setattr(config, "COVER_LETTER_DIR", ap_dir / "cover_letters")
    (ap_dir / "cover_letters").mkdir(parents=True, exist_ok=True)
    (ap_dir / "resume.txt").write_text("Base resume", encoding="utf-8")
    (ap_dir / "profile.json").write_text(
        json.dumps(
            {
                "personal": {
                    "full_name": "Test User",
                    "email": "test@example.com",
                    "phone": "+15551234567",
                    "city": "Remote",
                },
                "work_authorization": {},
                "compensation": {},
            }
        ),
        encoding="utf-8",
    )

    role_dir = tmp_path / "role_resumes"
    role_dir.mkdir()
    pdf = role_dir / "backend-engineer.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    txt = role_dir / "backend-engineer.txt"
    txt.write_text("Python APIs PostgreSQL backend services", encoding="utf-8")
    (role_dir / "manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {
                        "key": "backend-engineer",
                        "title": "Backend Engineer",
                        "aliases": ["backend engineer"],
                        "keywords": ["python", "postgres"],
                        "pdf_path": str(pdf),
                        "txt_path": str(txt),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ROLE_RESUME_DIR", role_dir)

    stale_cl = ap_dir / "cover_letters" / "OtherCompany_Frontend_Dev_CL.txt"
    stale_cl.write_text("Frontend-only cover letter.", encoding="utf-8")

    job = {
        "title": "Senior Python Backend Engineer",
        "site": "OtherCompany",
        "full_description": "Build Python APIs and PostgreSQL services.",
        "cover_letter_path": str(stale_cl),
        "tailored_resume_path": str(pdf),
    }

    with patch(
        "applypilot.apply.cover_resolve.generate_cover_letter_with_routing",
        return_value=("Backend-aligned cover.", {"source": "llm"}),
    ) as gen:
        text, txt_path, _pdf_upload = cover_resolve.resolve_apply_cover_letter(job)

    gen.assert_called_once()
    assert "Backend-aligned" in text
    assert "role_backend-engineer" in txt_path

