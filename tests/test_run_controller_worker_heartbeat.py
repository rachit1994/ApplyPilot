"""Tests for worker heartbeat parsing from apply launcher log lines."""

from __future__ import annotations

from applypilot.orchestration.run_controller import _parse_worker_log_line


def test_parse_worker_log_line_with_structured_status():
    payload = _parse_worker_log_line(
        "[worker-2] status=paused_quota PAUSED: Claude quota — check session limit"
    )
    assert payload == {
        "worker_id": 2,
        "status": "paused_quota",
        "detail": "PAUSED: Claude quota — check session limit",
    }


def test_parse_worker_log_line_without_status():
    payload = _parse_worker_log_line("[worker-0] Launching Chrome for ExampleCo")
    assert payload == {
        "worker_id": 0,
        "detail": "Launching Chrome for ExampleCo",
    }


def test_parse_worker_log_line_non_worker_returns_none():
    assert _parse_worker_log_line("INFO - unrelated log line") is None
