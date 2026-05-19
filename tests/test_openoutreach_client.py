"""OpenOutreach client tests with mocked HTTP."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from applypilot.outreach.openoutreach_client import (
    OpenOutreachClient,
    OpenOutreachError,
    check_openoutreach_health,
)


def _mock_response(status: int, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = ""
    if json_body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = json_body
    return resp


@patch("applypilot.outreach.openoutreach_client.httpx.Client")
def test_connect_success(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.request.return_value = _mock_response(200, {"status": "ok"})

    client = OpenOutreachClient("http://127.0.0.1:8741/v1", "secret")
    body = client.connect("jane-doe", campaign="job-referrals")
    assert body["status"] == "ok"
    mock_client.request.assert_called_once()
    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["json"]["public_id"] == "jane-doe"


@patch("applypilot.outreach.openoutreach_client.httpx.Client")
def test_message_conversation_via(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.request.return_value = _mock_response(200, {"sent": True})

    client = OpenOutreachClient("http://127.0.0.1:8741/v1", "secret")
    urn = "urn:li:msg_conversation:(urn:li:fsd_profile:abc,2-xyz)"
    client.message(
        "jane-doe",
        "hi",
        conversation_urn=urn,
        via="conversation",
    )
    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["json"]["via"] == "conversation"
    assert call_kwargs["json"]["conversation_urn"] == urn


@patch("applypilot.outreach.openoutreach_client.httpx.Client")
def test_connect_rate_limit(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.request.return_value = _mock_response(429, {"detail": "rate limited"})

    client = OpenOutreachClient("http://127.0.0.1:8741/v1", "secret")
    with pytest.raises(OpenOutreachError) as exc:
        client.connect("jane-doe")
    assert exc.value.status_code == 429


@patch("applypilot.outreach.openoutreach_client.OpenOutreachClient.health")
def test_check_health_onboarded(mock_health: MagicMock) -> None:
    mock_health.return_value = {"ok": True, "onboarded": True}
    ok, note = check_openoutreach_health("http://127.0.0.1:8741/v1", "key")
    assert ok is True
    assert "onboarded" in note


def test_check_health_missing_key() -> None:
    ok, note = check_openoutreach_health("http://127.0.0.1:8741/v1", "")
    assert ok is False
    assert "OPENOUTREACH_API_KEY" in note


@patch("applypilot.outreach.openoutreach_client.httpx.Client")
def test_connection_refused_raises_openoutreach_error(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_client.request.side_effect = httpx.ConnectError(
        "[Errno 61] Connection refused",
        request=httpx.Request("GET", "http://127.0.0.1:8741/v1/health"),
    )

    client = OpenOutreachClient("http://127.0.0.1:8741/v1", "secret")
    with pytest.raises(OpenOutreachError) as exc:
        client.health()
    assert "cannot connect to OpenOutreach" in str(exc.value)
    assert "applypilot openoutreach start" in str(exc.value)
