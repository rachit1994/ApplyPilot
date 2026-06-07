from __future__ import annotations

from pathlib import Path

import pytest

from applypilot import config
from applypilot import database
from applypilot.job_log import extract_job_url_from_message, format_job_line, lookup_job_by_artifact


def test_format_job_line_includes_url():
    line = format_job_line(
        {
            "title": "Senior Lead Software Engineer",
            "site": "LinkedIn",
            "url": "https://example.com/jobs/123",
        }
    )
    assert "Senior Lead Software Engineer @ LinkedIn" in line
    assert "https://example.com/jobs/123" in line


def test_format_job_line_truncates_long_title():
    line = format_job_line(title="X" * 80, url="https://a.test/1")
    assert len(line.split("|", 1)[0].strip()) <= 50


def test_extract_job_url_from_message():
    line = format_job_line(
        title="Engineer",
        url="https://example.com/jobs/123",
    )
    assert extract_job_url_from_message(line) == "https://example.com/jobs/123"
    assert extract_job_url_from_message("URL: https://boards.example/job/9") == "https://boards.example/job/9"
    assert extract_job_url_from_message("no url here") is None


def test_lookup_job_by_artifact(tmp_path: Path, monkeypatch, isolated_db):
    cl_path = tmp_path / "cover_letters" / "linkedin_Role_CL.txt"
    cl_path.parent.mkdir(parents=True)
    cl_path.write_text("letter", encoding="utf-8")

    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    database.close_connection()
    database.init_db()
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO jobs (url, title, site, cover_letter_path)
        VALUES ('https://jobs.test/1', 'Role', 'LinkedIn', ?)
        """,
        (str(cl_path),),
    )
    conn.commit()

    match = lookup_job_by_artifact(cl_path, conn=conn)
    assert match is not None
    assert match["url"] == "https://jobs.test/1"

    database.close_connection()
