from pathlib import Path

from applypilot.apply.apply_log_parser import (
    build_form_filled_record,
    extract_fields_from_fill_actions,
    extract_fill_actions,
    extract_last_form_snapshot,
    extract_result_json,
    extract_result_status,
    parse_apply_log,
    session_log_incomplete,
)

SAMPLE_LOG = """
Some preamble
>> Filled input[name=email] with user@example.com
>> Uploaded resume.pdf
browser snapshot {"fieldCount": 2, "url": "https://jobs.example.com/apply", "fields": [
  {"label": "Email", "value": "user@example.com", "empty": false},
  {"label": "Phone", "value": "", "empty": true}
], "visibleErrors": ["Required field missing"]}
RESULT: applied — confirmation page visible
"""


def test_extract_fill_actions_dedupes():
    actions = extract_fill_actions(">> click submit\n>> click submit\n>> fill name")
    assert actions == ["click submit", "fill name"]


def test_extract_last_form_snapshot():
    snap = extract_last_form_snapshot(SAMPLE_LOG)
    assert snap is not None
    assert snap["fieldCount"] == 2
    assert snap["url"] == "https://jobs.example.com/apply"


def test_extract_result_status_from_end():
    assert extract_result_status(SAMPLE_LOG) == "RESULT: applied — confirmation page visible"


def test_parse_apply_log_shapes_fields():
    parsed = parse_apply_log(SAMPLE_LOG)
    assert parsed["result_line"] == "RESULT: applied — confirmation page visible"
    assert len(parsed["fill_actions"]) == 2
    assert parsed["fields"][0]["label"] == "Email"
    assert parsed["fields"][1]["empty"] is True
    assert parsed["visible_errors"] == ["Required field missing"]


INCOMPLETE_LOG = """
>> browser_fill email user@example.com
browser snapshot {"fieldCount": 1, "url": "https://apply.example.com", "fields": []}
"""


def test_session_log_incomplete_without_result(tmp_path: Path):
    log_file = tmp_path / "session.log"
    log_file.write_text(INCOMPLETE_LOG, encoding="utf-8")
    assert session_log_incomplete(log_file) is True


def test_session_log_incomplete_false_when_result_present(tmp_path: Path):
    log_file = tmp_path / "session.log"
    log_file.write_text(INCOMPLETE_LOG + "\nRESULT:APPLIED\n", encoding="utf-8")
    assert session_log_incomplete(log_file) is False


RESULT_JSON_LOG = """
>> browser_click submit-ref Submit
RESULT_JSON:{"status":"applied","submit_click_ref":"submit-ref","submit_button_text":"Submit","pre_submit_url":"https://jobs.example.com/apply","post_submit_url":"https://jobs.example.com/thanks","post_submit_snapshot":{"fieldCount":0,"fields":[]},"confirmation_copy":"Application received"}
"""


def test_extract_result_json_happy():
    parsed = extract_result_json(RESULT_JSON_LOG)
    assert parsed is not None
    assert parsed["status"] == "applied"
    assert parsed["submit_click_ref"] == "submit-ref"
    assert parsed["post_submit_snapshot"]["fieldCount"] == 0


def test_extract_result_json_multiline():
    parsed = extract_result_json(
        """
Agent final answer:
RESULT_JSON:{
  "status": "applied",
  "submit_click_ref": "submit-ref",
  "submit_button_text": "Submit",
  "pre_submit_url": "https://jobs.example.com/apply",
  "post_submit_url": "https://jobs.example.com/thanks",
  "post_submit_snapshot": {
    "fieldCount": 0,
    "fields": []
  },
  "confirmation_copy": "Application received"
}
"""
    )
    assert parsed is not None
    assert parsed["status"] == "applied"
    assert parsed["post_submit_snapshot"]["fieldCount"] == 0


def test_extract_result_json_missing():
    assert extract_result_json(SAMPLE_LOG) is None


def test_extract_result_json_malformed():
    assert extract_result_json('RESULT_JSON:{"status":') is None


def test_extract_result_status_skips_result_json_line():
    log = 'noise\nRESULT_JSON:{"status":"failed"}\nRESULT:APPLIED\n'
    assert extract_result_status(log) == "RESULT:APPLIED"


def test_extract_fields_from_fill_actions():
    actions = [
        "browser_fill email user@example.com",
        "browser_fill textarea message Hello — interested in the role",
        "Filled input[name=phone] with +1-555-0100",
    ]
    fields = extract_fields_from_fill_actions(actions)
    labels = {f["label"] for f in fields}
    assert "email" in labels
    assert "textarea message" in labels
    assert "input[name=phone]" in labels
    by_label = {f["label"]: f["value"] for f in fields}
    assert by_label["email"] == "user@example.com"
    assert "Hello" in by_label["textarea message"]


def test_build_form_filled_record_merges_snapshot_and_actions():
    log = """
>> browser_fill email user@example.com
browser snapshot {"fieldCount": 2, "url": "https://jobs.example/apply", "fields": [
  {"label": "Email", "value": "", "type": "text", "empty": true},
  {"label": "Phone", "value": "+1-555", "type": "tel", "empty": false}
], "visibleErrors": [], "emptyRequired": 1}
"""
    record = build_form_filled_record(log)
    assert record is not None
    assert record["field_count"] >= 2
    by_label = {f["label"]: f for f in record["fields"]}
    assert by_label["Email"]["value"] == "user@example.com"
    assert by_label["Phone"]["value"] == "+1-555"


def test_parse_apply_log_includes_result_json_and_verification():
    parsed = parse_apply_log(RESULT_JSON_LOG)
    assert parsed["result_json"] is not None
    assert parsed["result_json"]["status"] == "applied"
    assert parsed["verification"] is not None
    assert parsed["verification"]["decision"] == "verified"
    assert parsed["verification"]["reasons"] == []
    assert parsed["verification"]["submit_button_text"] == "Submit"
