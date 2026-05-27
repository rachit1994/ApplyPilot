import json
from pathlib import Path

import httpx
import pytest

from applypilot.apply import gmail_auth


def test_run_login_uses_gmail_mcp_package(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(gmail_auth, "GMAIL_MCP_DIR", tmp_path / ".gmail-mcp")
    monkeypatch.setattr(gmail_auth, "resolve_npx_command", lambda: "/opt/homebrew/bin/npx")
    monkeypatch.setattr(gmail_auth.subprocess, "run", fake_run)

    assert gmail_auth.run_login() == 0
    assert calls == [["/opt/homebrew/bin/npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp", "auth"]]
    assert (tmp_path / ".gmail-mcp").exists()


def test_list_recent_messages_refreshes_and_reads_metadata(monkeypatch, tmp_path):
    oauth_path = tmp_path / "gcp-oauth.keys.json"
    credentials_path = tmp_path / "credentials.json"
    oauth_path.write_text(
        json.dumps({"installed": {"client_id": "cid", "client_secret": "secret"}}),
        encoding="utf-8",
    )
    credentials_path.write_text(
        json.dumps({"refresh_token": "refresh", "expiry_date": 1}),
        encoding="utf-8",
    )

    monkeypatch.setattr(gmail_auth, "GMAIL_MCP_DIR", tmp_path)
    monkeypatch.setattr(gmail_auth, "OAUTH_KEYS_PATH", oauth_path)
    monkeypatch.setattr(gmail_auth, "CREDENTIALS_PATH", credentials_path)

    def fake_post(url, data, timeout):
        assert url == gmail_auth.GOOGLE_TOKEN_URL
        assert data["refresh_token"] == "refresh"
        return httpx.Response(
            200,
            json={"access_token": "fresh-token", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    def fake_get(url, headers, params, timeout):
        assert headers == {"Authorization": "Bearer fresh-token"}
        if url.endswith("/users/me/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": "m1"}, {"id": "m2"}]},
                request=httpx.Request("GET", url),
            )
        if url.endswith("/users/me/messages/m1"):
            return httpx.Response(
                200,
                json={
                    "snippet": "Code 123456",
                    "payload": {
                        "headers": [
                            {"name": "Date", "value": "Mon, 25 May 2026 10:00:00 +0000"},
                            {"name": "From", "value": "Greenhouse <no-reply@greenhouse.io>"},
                            {"name": "Subject", "value": "Your verification code"},
                        ]
                    },
                },
                request=httpx.Request("GET", url),
            )
        if url.endswith("/users/me/messages/m2"):
            return httpx.Response(
                200,
                json={
                    "snippet": "Welcome",
                    "payload": {
                        "headers": [
                            {"name": "Date", "value": "Mon, 25 May 2026 09:00:00 +0000"},
                            {"name": "From", "value": "Someone <person@example.com>"},
                            {"name": "Subject", "value": "Hello"},
                        ]
                    },
                },
                request=httpx.Request("GET", url),
            )
        raise AssertionError(url)

    monkeypatch.setattr(gmail_auth.httpx, "post", fake_post)
    monkeypatch.setattr(gmail_auth.httpx, "get", fake_get)

    messages = gmail_auth.list_recent_messages(limit=2)

    assert [m.message_id for m in messages] == ["m1", "m2"]
    assert messages[0].from_ == "Greenhouse <no-reply@greenhouse.io>"
    assert messages[0].subject == "Your verification code"
    saved = json.loads(credentials_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "fresh-token"
    assert saved["refresh_token"] == "refresh"
    assert saved["expiry_date"] > 1


def test_missing_credentials_gives_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr(gmail_auth, "CREDENTIALS_PATH", tmp_path / "credentials.json")

    with pytest.raises(FileNotFoundError, match="applypilot gmail login"):
        gmail_auth.list_recent_messages()
