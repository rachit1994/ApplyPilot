"""Classifier parsing and threshold behavior."""

import json

import pytest

from applypilot.inbox.classifier import _parse_json_object, classify_message


def test_parse_json_object_strips_fence():
    raw = '```json\n{"is_job_related": true, "confidence": 0.9}\n```'
    data = _parse_json_object(raw)
    assert data["is_job_related"] is True
    assert data["confidence"] == 0.9


def test_classify_message_uses_client(monkeypatch):
    class FakeClient:
        def chat(self, **kwargs):
            return json.dumps(
                {
                    "asked_to_apply": True,
                    "confidence": 0.95,
                    "extracted_title": "Software Engineer",
                    "extracted_company": "Acme",
                    "reasoning": "Explicit apply request.",
                }
            )

    result = classify_message(
        "Please apply for Software Engineer at Acme using this link.",
        client=FakeClient(),
        threshold=0.7,
    )
    assert result["asked_to_apply"] is True
    assert result["is_job_related"] is True
    assert result["extracted_title"] == "Software Engineer"
    assert result["confidence"] == 0.95


def test_classify_below_threshold_not_job():
    class FakeClient:
        def chat(self, **kwargs):
            return json.dumps(
                {
                    "asked_to_apply": True,
                    "confidence": 0.5,
                    "extracted_title": None,
                    "extracted_company": None,
                    "reasoning": "Weak signal.",
                }
            )

    result = classify_message("Maybe we should chat sometime.", client=FakeClient(), threshold=0.7)
    assert result["asked_to_apply"] is False
    assert result["is_job_related"] is False
