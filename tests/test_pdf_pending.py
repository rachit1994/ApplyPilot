from pathlib import Path

import applypilot.scoring.pdf as pdf_mod
from applypilot.scoring.pdf import batch_convert, pending_pdf_conversions


def test_pending_pdf_conversions_counts_missing_sibling_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_mod, "TAILORED_DIR", tmp_path)
    (tmp_path / "resume_a.txt").write_text("A", encoding="utf-8")
    (tmp_path / "resume_b.txt").write_text("B", encoding="utf-8")
    (tmp_path / "resume_b.pdf").write_bytes(b"%PDF")

    assert pending_pdf_conversions() == 1


def test_batch_convert_no_info_spam_when_nothing_to_do(tmp_path, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(pdf_mod, "TAILORED_DIR", tmp_path)
    (tmp_path / "done.txt").write_text("x", encoding="utf-8")
    (tmp_path / "done.pdf").write_bytes(b"%PDF")

    with caplog.at_level(logging.INFO):
        assert batch_convert() == 0

    assert not any("already have PDFs" in r.message for r in caplog.records)
