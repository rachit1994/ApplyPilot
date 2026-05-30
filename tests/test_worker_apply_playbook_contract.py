"""Contract tests: playbook doc tables and rendered prompt fidelity."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from applypilot.apply.worker_playbook import (
    build_playbook_tokens,
    default_playbook_path,
    load_playbook_markdown,
    render_worker_playbook_prompt,
)

PLAYBOOK_PATH = default_playbook_path()

STOP_CHECK_LINES = [
    "RESULT:failed:sso_required",
    "RESULT:failed:unsafe_verification",
    "RESULT:failed:not_a_job_application",
    "RESULT:failed:expired",
    "RESULT:failed:unsafe_data",
]

DONE_CHECK_LINES = [
    "RESULT:applied",
    "RESULT:needs_email_code",
    "RESULT:captcha",
    "RESULT:failed:stuck",
]

FREE_TEXT_TEMPLATE = (
    "I have {{years_experience}} years of experience as a {{current_job_title}} "
    "and my background maps directly to this role. I am available to start "
    "{{earliest_start_date}} and based in {{city}}."
)


def _count_table_rows(section: str, after_heading: str) -> int:
    start = section.find(after_heading)
    assert start >= 0
    chunk = section[start:]
    next_h = chunk.find("\n## ", 1)
    if next_h > 0:
        chunk = chunk[:next_h]
    rows = re.findall(r"^\|[^|]+\|[^|]+\|", chunk, flags=re.MULTILINE)
    data_rows = [r for r in rows if not re.match(r"^\|\s*---", r)]
    return len(data_rows)


def test_playbook_doc_has_stop_field_question_tables():
    body = load_playbook_markdown(PLAYBOOK_PATH)
    assert _count_table_rows(body, "## STOP CHECK") >= 5
    assert _count_table_rows(body, "## FIELD MAP") >= 1
    assert _count_table_rows(body, "## QUESTION MAP") >= 1


def test_playbook_doc_stop_and_done_result_lines():
    body = load_playbook_markdown(PLAYBOOK_PATH)
    for line in STOP_CHECK_LINES + DONE_CHECK_LINES:
        assert line in body


def test_playbook_doc_free_text_template_verbatim():
    body = load_playbook_markdown(PLAYBOOK_PATH)
    assert FREE_TEXT_TEMPLATE in body


def test_playbook_doc_pre_submit_rules():
    body = load_playbook_markdown(PLAYBOOK_PATH)
    assert "at most twice" in body.lower() or "Do this at most twice" in body
    assert "emptyRequired` > 0" in body or "emptyRequired` is still > 0" in body
    assert "Never click Submit while `emptyRequired` > 0" in body


def test_rendered_prompt_preserves_stop_and_done_lines(tmp_path: Path):
    profile = {
        "personal": {
            "full_name": "A B",
            "preferred_name": "A",
            "email": "a@b.com",
            "phone": "555",
            "address": "",
            "city": "X",
            "province_state": "",
            "country": "",
            "postal_code": "",
        },
        "work_authorization": {
            "legally_authorized_to_work": "Yes",
            "require_sponsorship": "No",
            "work_permit_type": "",
        },
        "compensation": {"salary_expectation": "1", "salary_currency": "USD"},
        "experience": {
            "years_of_experience_total": "5",
            "education_level": "BS",
            "current_job_title": "Eng",
        },
        "availability": {"earliest_start_date": "Now"},
    }
    job = {
        "url": "https://example.com/job",
        "application_url": "https://example.com/job",
        "tailored_resume_path": str(tmp_path / "r.pdf"),
    }
    (tmp_path / "r.pdf").write_bytes(b"%PDF")
    tokens = build_playbook_tokens(profile, job, resume_pdf_path=str(tmp_path / "r.pdf"))
    rendered = render_worker_playbook_prompt(tokens, include_tool_aliases=False)
    for line in STOP_CHECK_LINES + DONE_CHECK_LINES:
        assert line in rendered
    assert job["url"] in rendered
    assert "`navigate` to `https://example.com/job`" in rendered
