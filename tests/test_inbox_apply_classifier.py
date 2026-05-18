"""Strict apply-request classification fixtures (real Other-tab patterns)."""

import json

import pytest

from applypilot.inbox.classifier import classify_thread_text


class _FixedClassifier:
    def __init__(self, payload: dict):
        self._payload = payload

    def chat(self, **kwargs):
        return json.dumps(self._payload)


@pytest.mark.parametrize(
    "transcript,expected",
    [
        (
            "Them: We'd love for you to take the next step by applying through our official form:\n"
            "https://example.com/apply",
            True,
        ),
        (
            "Them: The feedback was generally very good. Fitment for the current role is still under review. "
            "It will take few more days. I will keep you posted.",
            False,
        ),
        (
            "Them: Budget is max 30L. Don't think you will fit in our budget",
            False,
        ),
        (
            "Them: sorry that my client will not offer EP application atm.",
            False,
        ),
        (
            "Them: We have an opportunity for Reactjs profile. Please share your updated Cv so we can discuss.",
            True,
        ),
    ],
)
def test_classify_thread_text_fixtures(transcript: str, expected: bool):
    intent = "apply_request" if expected else "status_update"
    payload = {
        "intent": intent,
        "confidence": 0.92,
        "extracted_title": None,
        "extracted_company": None,
        "reasoning": "fixture",
    }
    result = classify_thread_text(transcript, client=_FixedClassifier(payload), threshold=0.7)
    assert result["asked_to_apply"] is expected
    assert result["is_job_related"] is expected
