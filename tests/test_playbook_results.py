"""Table-driven tests for worker-apply-playbook RESULT lines."""

from __future__ import annotations

import pytest

from applypilot.apply.playbook_results import (
    PLAYBOOK_TO_LAUNCHER,
    parse_playbook_result_line,
    resolve_playbook_result,
)

# Exact terminal lines from docs/worker-apply-playbook.md (STOP + DONE + stuck rule).
PLAYBOOK_RESULT_CASES = [
    ("RESULT:failed:sso_required", "failed:sso_required"),
    ("RESULT:failed:unsafe_verification", "failed:unsafe_verification"),
    ("RESULT:failed:not_a_job_application", "failed:not_a_job_application"),
    ("RESULT:failed:expired", "expired"),
    ("RESULT:failed:unsafe_data", "failed:unsafe_data"),
    ("RESULT:applied", "submitted_unverified:playbook_applied"),
    ("RESULT:needs_email_code", "failed:needs_email_code"),
    ("RESULT:captcha", "captcha"),
    ("RESULT:failed:stuck", "failed:stuck"),
]


@pytest.mark.parametrize("line,expected", PLAYBOOK_RESULT_CASES)
def test_resolve_playbook_result_exact_lines(line: str, expected: str) -> None:
    output = f"Filled form.\n{line}\n"
    assert resolve_playbook_result(output) == expected


_CASE_INSENSITIVE_LINES = [
    case for case in PLAYBOOK_RESULT_CASES if case[0] != "RESULT:applied"
]


@pytest.mark.parametrize("line,expected", _CASE_INSENSITIVE_LINES)
def test_resolve_playbook_result_case_insensitive(line: str, expected: str) -> None:
    upper = line.upper()
    output = f"Done.\n{upper}\n"
    assert resolve_playbook_result(output) == expected


def test_parse_playbook_result_line_uses_last_matching_line() -> None:
    output = "RESULT:failed:stuck\nnoise\nRESULT:applied\n"
    assert parse_playbook_result_line(output) == "applied"


def test_resolve_playbook_result_unknown_line_returns_none() -> None:
    assert resolve_playbook_result("RESULT:failed:unknown_reason") is None


def test_playbook_map_covers_all_documented_outcomes() -> None:
    assert len(PLAYBOOK_TO_LAUNCHER) == len(PLAYBOOK_RESULT_CASES)


def test_legacy_uppercase_applied_is_not_playbook_applied() -> None:
    assert resolve_playbook_result("RESULT:APPLIED\n") is None
    assert (
        resolve_playbook_result("RESULT:applied\n")
        == "submitted_unverified:playbook_applied"
    )
