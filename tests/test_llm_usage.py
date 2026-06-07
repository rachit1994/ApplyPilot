from __future__ import annotations

import httpx


def test_record_llm_usage_monthly_rollup(tmp_path, monkeypatch):
    from applypilot import config, database
    database.close_connection()
    database.init_db()

    database.record_llm_usage(
        provider="gemini",
        model="gemini-2.5-flash-lite",
        operation="score_batch",
        input_tokens=1000,
        output_tokens=200,
        estimated=False,
        cost_usd=0.000072,
        created_at="2026-05-27T10:00:00+00:00",
    )

    rows = database.get_llm_usage_monthly(month="2026-05")

    assert rows == [
        {
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "operation": "score_batch",
            "calls": 1,
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_tokens": 0,
            "cache_create_tokens": 0,
            "cost_usd": 0.000072,
            "estimated_calls": 0,
        }
    ]


def test_compat_llm_response_records_usage_metadata(monkeypatch):
    from applypilot.llm import LLMClient
    import applypilot.llm as llm

    captured: dict = {}
    monkeypatch.setattr(llm, "_record_usage_event", lambda **kwargs: captured.update(kwargs))
    response = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        },
        request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"),
    )

    text = LLMClient._handle_compat_response(
        response,
        provider="gemini",
        model="gemini-2.5-flash-lite",
        operation="cover_letter",
        prompt_messages=[{"role": "user", "content": "hello"}],
    )

    assert text == "OK"
    assert captured["provider"] == "gemini"
    assert captured["operation"] == "cover_letter"
    assert captured["input_tokens"] == 12
    assert captured["output_tokens"] == 3
    assert captured["estimated"] is False
