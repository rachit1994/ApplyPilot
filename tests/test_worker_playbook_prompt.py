"""Tests for worker apply playbook prompt rendering."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from applypilot import config
from applypilot.apply import prompt as prompt_mod
from applypilot.apply.worker_playbook import (
    build_playbook_tokens,
    build_worker_apply_prompt,
    default_playbook_path,
    load_playbook_markdown,
    render_worker_playbook_prompt,
)
from applypilot.apply.worker_playbook_tools import build_tool_alias_section


def _minimal_profile() -> dict:
    return {
        "personal": {
            "full_name": "Test User",
            "preferred_name": "Test",
            "email": "test@example.com",
            "phone": "+1 555 0100",
            "address": "1 Main",
            "city": "Bangalore",
            "province_state": "KA",
            "country": "India",
            "postal_code": "560001",
            "linkedin_url": "https://linkedin.com/in/test",
            "github_url": "https://github.com/test",
            "portfolio_url": "",
            "password": "secret",
        },
        "work_authorization": {
            "legally_authorized_to_work": "Yes",
            "require_sponsorship": "No",
            "work_permit_type": "",
        },
        "compensation": {"salary_expectation": "4000000", "salary_currency": "INR"},
        "experience": {
            "years_of_experience_total": "10",
            "education_level": "Bachelor's",
            "current_job_title": "Engineer",
        },
        "availability": {"earliest_start_date": "Immediately"},
        "eeo_voluntary": {},
    }


def _job_for(base: Path) -> dict:
    pdf = base / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    return {
        "url": "https://boards.greenhouse.io/acme/jobs/123",
        "application_url": "https://boards.greenhouse.io/acme/jobs/123",
        "title": "Engineer",
        "site": "Acme",
        "tailored_resume_path": str(pdf),
        "fit_score": 9,
    }


def test_default_playbook_path_exists():
    path = default_playbook_path()
    assert path.is_file()
    assert path.name == "worker-apply-playbook.md"


def test_load_playbook_markdown_has_step_order():
    body = load_playbook_markdown()
    assert "## STEP ORDER" in body
    assert "Max 12 actions total" in body


def test_render_worker_playbook_prompt_substitutes_tokens(tmp_path: Path):
    tokens = build_playbook_tokens(
        _minimal_profile(),
        _job_for(tmp_path),
        resume_pdf_path="/tmp/Test_User_Resume.pdf",
    )
    rendered = render_worker_playbook_prompt(tokens, include_tool_aliases=False)
    assert "{{" not in rendered
    assert "test@example.com" in rendered
    assert "/tmp/Test_User_Resume.pdf" in rendered
    for heading in (
        "STEP ORDER",
        "STOP CHECK",
        "FIELD MAP",
        "QUESTION MAP",
        "PRE-SUBMIT CHECK",
        "DONE CHECK",
        "HARD RULES",
    ):
        assert heading in rendered or f"## {heading}" in rendered


def test_render_includes_tool_aliases_and_form_verify(tmp_path: Path):
    tokens = build_playbook_tokens(
        _minimal_profile(),
        _job_for(tmp_path),
        resume_pdf_path="/tmp/resume.pdf",
    )
    rendered = render_worker_playbook_prompt(tokens)
    assert "browser_navigate" in rendered
    assert "browser_evaluate" in rendered
    assert "emptyRequired" in rendered
    assert "visibleErrors" in rendered
    alias_only = build_tool_alias_section()
    assert "browser_fill_form" in alias_only


def test_build_worker_apply_prompt_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLY_WORKER_DIR", tmp_path / "workers")
    monkeypatch.setattr(config, "load_profile", lambda: _minimal_profile())

    def fake_ensure_resume_pdf(path: str | Path) -> Path:
        pdf = Path(path)
        if pdf.suffix.lower() != ".pdf":
            pdf = pdf.with_suffix(".pdf")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        if not pdf.exists():
            pdf.write_bytes(b"%PDF-1.4\n")
        return pdf.resolve()

    monkeypatch.setattr(prompt_mod, "ensure_resume_pdf", fake_ensure_resume_pdf)

    job = _job_for(tmp_path)
    prompt = build_worker_apply_prompt(job, upload_dir=tmp_path / "w0")
    assert "RESULT:failed:stuck" in prompt
    assert "RESULT_JSON" not in prompt
    assert re.search(r"Test_User_Resume\.pdf", prompt)
