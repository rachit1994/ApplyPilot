"""Regression tests for launcher-side apply result resolution."""

from __future__ import annotations

from pathlib import Path

from applypilot.apply.launcher import _resolve_apply_result


def _resolve(output: str, tmp_path: Path) -> str:
    return _resolve_apply_result(
        output=output,
        worker_id=0,
        job={"title": "Founding Engineer", "company": "ExampleCo"},
        elapsed=123,
        job_log=tmp_path / "apply.log",
    )


def test_legacy_result_applied_without_evidence_is_unverified(tmp_path: Path):
    result = _resolve(
        """
Filled the application form.
RESULT:APPLIED
""",
        tmp_path,
    )

    assert result.startswith("submitted_unverified:")
    assert "legacy RESULT:APPLIED" in result


def test_dry_run_leakage_with_result_applied_is_unverified(tmp_path: Path):
    result = _resolve(
        """
The message is filled in correctly and the Send button is now active.
Per dry-run instructions, not clicking Send.
RESULT:APPLIED
""",
        tmp_path,
    )

    assert result.startswith("submitted_unverified:")
    assert not result.startswith("applied")


def test_structured_result_json_with_submit_evidence_is_applied(tmp_path: Path):
    result = _resolve(
        """
>> browser_fill textarea message Hello team
>> browser_click submit-ref Send
RESULT_JSON:{"status":"applied","submit_click_ref":"submit-ref","submit_button_text":"Send","pre_submit_url":"https://www.workatastartup.com/application?signup_job_id=1","post_submit_url":"https://www.workatastartup.com/messages/sent","post_submit_snapshot":{"fieldCount":0,"fields":[]},"confirmation_copy":"Message sent","screenshot_path":"/tmp/apply-proof.png"}
""",
        tmp_path,
    )

    assert result == "applied"
