"""Tests for apply ghost-fix Tier 1 verification gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot.apply.apply_log_parser import extract_fill_actions, extract_result_json
from applypilot.apply.verification import (
    VerificationRecord,
    evaluate,
    record_from_legacy_applied,
    record_from_result_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "apply_ghost"


def _load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _ghost_record_from_fixture(filename: str) -> VerificationRecord:
    text = _load_fixture(filename)
    return record_from_legacy_applied(fill_actions=extract_fill_actions(text))


@pytest.mark.parametrize(
    "fixture_name",
    [
        "billiontoone.txt",
        "camber.txt",
        "nova_credit.txt",
        "pine_park_health.txt",
        "aqua.txt",
    ],
)
def test_ghost_fixtures_downgrade(fixture_name: str):
    record = _ghost_record_from_fixture(fixture_name)
    verdict = evaluate(record)
    assert verdict.decision == "unverified"
    assert verdict.reasons


def test_verifier_accepts_structured_confirmation_without_tool_click_log():
    record = VerificationRecord(
        status="applied",
        submit_click_ref="btn-1",
        submit_button_text="Send",
        pre_submit_url="https://apply.example.com/form",
        post_submit_url="https://apply.example.com/thanks",
        post_submit_snapshot={"fieldCount": 0, "fields": []},
        confirmation_copy="Thank you",
        screenshot_path=None,
        fill_actions=["browser_fill email user@example.com"],
    )
    verdict = evaluate(record)
    assert verdict.decision == "verified"
    assert verdict.reasons == ()


def test_verifier_downgrades_unchanged_url_no_confirmation():
    record = VerificationRecord(
        status="applied",
        submit_click_ref="send-ref",
        submit_button_text="Send",
        pre_submit_url="https://apply.example.com/form",
        post_submit_url="https://apply.example.com/form",
        post_submit_snapshot={"fieldCount": 0, "fields": []},
        confirmation_copy=None,
        screenshot_path=None,
        fill_actions=["browser_click send-ref Send"],
    )
    verdict = evaluate(record)
    assert verdict.decision == "unverified"
    assert any("unchanged" in r for r in verdict.reasons)


def test_verifier_downgrades_form_still_rendered():
    record = VerificationRecord(
        status="applied",
        submit_click_ref="submit-ref",
        submit_button_text="Submit Application",
        pre_submit_url="https://apply.example.com/form",
        post_submit_url="https://apply.example.com/done",
        post_submit_snapshot={"fieldCount": 3, "fields": [{"label": "Name", "empty": True}]},
        confirmation_copy=None,
        screenshot_path=None,
        fill_actions=["browser_click submit-ref Submit Application"],
    )
    verdict = evaluate(record)
    assert verdict.decision == "unverified"
    assert any("form still rendered" in r for r in verdict.reasons)


def test_verifier_accepts_clean_applied_with_full_proof():
    record = VerificationRecord(
        status="applied",
        submit_click_ref="send-ref",
        submit_button_text="Send",
        pre_submit_url="https://www.workatastartup.com/application?job=1",
        post_submit_url="https://www.workatastartup.com/messages/sent",
        post_submit_snapshot={"fieldCount": 0, "fields": []},
        confirmation_copy="Message sent",
        screenshot_path="/tmp/apply-proof.png",
        fill_actions=[
            "browser_fill textarea message Hello",
            "browser_click send-ref Send",
        ],
    )
    verdict = evaluate(record)
    assert verdict.decision == "verified"
    assert verdict.reasons == ()


def test_verifier_accepts_confirmation_copy_when_tool_click_is_not_logged():
    record = VerificationRecord(
        status="applied",
        submit_click_ref="send-ref",
        submit_button_text="Submit application",
        pre_submit_url="https://apply.example.com/form",
        post_submit_url="https://apply.example.com/form",
        post_submit_snapshot={"heading": "Thank you for applying.", "fieldCount": 0},
        confirmation_copy="Thank you for applying. Your application was submitted.",
        screenshot_path=None,
        fill_actions=["browser_fill email user@example.com"],
    )
    verdict = evaluate(record)
    assert verdict.decision == "verified"
    assert verdict.reasons == ()


def test_verifier_passes_through_failed_unchanged():
    record = VerificationRecord(
        status="failed",
        submit_click_ref=None,
        submit_button_text=None,
        pre_submit_url=None,
        post_submit_url=None,
        post_submit_snapshot=None,
        confirmation_copy=None,
        screenshot_path=None,
        fill_actions=[],
    )
    verdict = evaluate(record)
    assert verdict.decision == "failed"
    assert verdict.reasons == ()


def test_legacy_freeform_RESULT_APPLIED_downgrades():
    record = _ghost_record_from_fixture("billiontoone.txt")
    verdict = evaluate(record)
    assert verdict.decision == "unverified"
    assert "RESULT:APPLIED" in _load_fixture("billiontoone.txt")
    assert not any("click" in a.lower() and "send" in a.lower() for a in record.fill_actions)


def test_apply_log_parser_extracts_RESULT_JSON_from_messy_output():
    messy = """
Agent thinking...
Some stderr noise
RESULT_JSON:{"status":"applied","submit_click_ref":"r1","submit_button_text":"Send","pre_submit_url":"https://a.com","post_submit_url":"https://a.com/ok","post_submit_snapshot":{"fieldCount":0},"confirmation_copy":"Thanks"}
trailing log line
"""
    parsed = extract_result_json(messy)
    assert parsed is not None
    assert parsed["status"] == "applied"
    assert parsed["submit_button_text"] == "Send"
    record = record_from_result_json(parsed, fill_actions=["browser_click r1 Send"])
    assert evaluate(record).decision == "verified"


def test_RESULT_JSON_malformed_falls_back():
    text = 'RESULT_JSON:{"status":"applied","submit_click_ref":broken'
    assert extract_result_json(text) is None
    legacy = record_from_legacy_applied(fill_actions=extract_fill_actions(text))
    assert evaluate(legacy).decision == "unverified"
