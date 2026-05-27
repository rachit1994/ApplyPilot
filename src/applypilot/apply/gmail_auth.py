"""Gmail MCP authentication helpers for autonomous apply verification codes."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

GMAIL_MCP_DIR = Path.home() / ".gmail-mcp"
OAUTH_KEYS_PATH = GMAIL_MCP_DIR / "gcp-oauth.keys.json"
CREDENTIALS_PATH = GMAIL_MCP_DIR / "credentials.json"
GMAIL_MCP_PACKAGE = "@gongrzhe/server-gmail-autoauth-mcp"

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class GmailMessageSummary:
    message_id: str
    date: str
    from_: str
    subject: str
    snippet: str


def resolve_npx_command() -> str:
    """Find npx even when ApplyPilot is launched from a sparse GUI PATH."""
    found = shutil.which("npx")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/bin/npx",
        "/usr/local/bin/npx",
        str(Path.home() / ".local/bin/npx"),
    ):
        if Path(candidate).exists():
            return candidate
    return "npx"


def oauth_keys_exist() -> bool:
    return OAUTH_KEYS_PATH.exists()


def credentials_exist() -> bool:
    return CREDENTIALS_PATH.exists()


def run_login() -> int:
    """Run the Gmail MCP OAuth flow in the user's normal browser."""
    GMAIL_MCP_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [resolve_npx_command(), "-y", GMAIL_MCP_PACKAGE, "auth"]
    return subprocess.run(cmd).returncode


def _load_oauth_client() -> dict[str, str]:
    if not OAUTH_KEYS_PATH.exists():
        raise FileNotFoundError(
            f"OAuth keys not found at {OAUTH_KEYS_PATH}. "
            "Download Google OAuth client JSON and save it as gcp-oauth.keys.json."
        )
    data = json.loads(OAUTH_KEYS_PATH.read_text(encoding="utf-8"))
    client = data.get("installed") or data.get("web")
    if not client:
        raise ValueError("OAuth keys file must contain 'installed' or 'web' credentials.")
    return client


def _load_credentials() -> dict[str, Any]:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found at {CREDENTIALS_PATH}. Run `applypilot gmail login`."
        )
    return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))


def _save_credentials(credentials: dict[str, Any]) -> None:
    GMAIL_MCP_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(credentials), encoding="utf-8")


def _refresh_access_token(credentials: dict[str, Any]) -> dict[str, Any]:
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        raise ValueError("Gmail credentials are missing refresh_token. Run `applypilot gmail login` again.")

    client = _load_oauth_client()
    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    token_data = response.json()

    credentials.update(token_data)
    if "expires_in" in token_data:
        credentials["expiry_date"] = int((time.time() + int(token_data["expires_in"])) * 1000)
    credentials["refresh_token"] = refresh_token
    _save_credentials(credentials)
    return credentials


def _access_token() -> str:
    credentials = _load_credentials()
    expires_ms = int(credentials.get("expiry_date") or 0)
    # Refresh one minute early. If expiry is absent, try the current token first.
    if expires_ms and expires_ms <= int((time.time() + 60) * 1000):
        credentials = _refresh_access_token(credentials)
    token = credentials.get("access_token")
    if not token:
        credentials = _refresh_access_token(credentials)
        token = credentials.get("access_token")
    if not token:
        raise ValueError("Gmail credentials do not contain an access_token.")
    return str(token)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _metadata_header(payload: dict[str, Any], name: str) -> str:
    headers = payload.get("headers") or []
    for item in headers:
        if str(item.get("name", "")).lower() == name.lower():
            return str(item.get("value", ""))
    return ""


def list_recent_messages(limit: int = 3) -> list[GmailMessageSummary]:
    """Return recent Gmail inbox messages as a health check for the MCP token."""
    token = _access_token()
    params = {"maxResults": max(1, min(limit, 10)), "q": "newer_than:30d"}
    response = httpx.get(f"{GMAIL_API}/users/me/messages", headers=_headers(token), params=params, timeout=30.0)
    if response.status_code == 401:
        token = _refresh_access_token(_load_credentials())["access_token"]
        response = httpx.get(f"{GMAIL_API}/users/me/messages", headers=_headers(token), params=params, timeout=30.0)
    response.raise_for_status()

    messages = response.json().get("messages") or []
    summaries: list[GmailMessageSummary] = []
    for item in messages[:limit]:
        msg_id = item.get("id")
        if not msg_id:
            continue
        detail = httpx.get(
            f"{GMAIL_API}/users/me/messages/{msg_id}",
            headers=_headers(token),
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            timeout=30.0,
        )
        detail.raise_for_status()
        data = detail.json()
        payload = data.get("payload") or {}
        summaries.append(
            GmailMessageSummary(
                message_id=str(msg_id),
                date=_metadata_header(payload, "Date"),
                from_=_metadata_header(payload, "From"),
                subject=_metadata_header(payload, "Subject"),
                snippet=str(data.get("snippet") or ""),
            )
        )
    return summaries

