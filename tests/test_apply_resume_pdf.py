"""Tests for tailored resume PDF resolution at apply time."""

from pathlib import Path

import pytest

from applypilot.apply.prompt import ensure_resume_pdf


def test_ensure_resume_pdf_returns_existing_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "Acme_Engineer.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    assert ensure_resume_pdf(pdf) == pdf.resolve()


def test_ensure_resume_pdf_generates_from_txt(tmp_path: Path, monkeypatch) -> None:
    txt = tmp_path / "Acme_Engineer.txt"
    txt.write_text("Name\nTitle\nExperience", encoding="utf-8")
    out_pdf = tmp_path / "Acme_Engineer.pdf"

    def fake_convert(text_path: Path) -> Path:
        out_pdf.write_bytes(b"%PDF-generated")
        return out_pdf

    monkeypatch.setattr(
        "applypilot.scoring.pdf.convert_to_pdf",
        fake_convert,
    )
    result = ensure_resume_pdf(txt)
    assert result == out_pdf.resolve()
    assert out_pdf.is_file()


def test_ensure_resume_pdf_raises_when_neither_exists(tmp_path: Path) -> None:
    missing = tmp_path / "Missing_Job.txt"
    with pytest.raises(ValueError, match="Resume PDF not found"):
        ensure_resume_pdf(missing)
