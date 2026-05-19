from applypilot.apply.apply_log_parser import (
    extract_fill_actions,
    extract_last_form_snapshot,
    extract_result_status,
    parse_apply_log,
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
