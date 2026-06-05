"""Gmail MCP authentication helpers for autonomous apply verification codes."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


@dataclass(frozen=True)
class GmailReceiptResult:
    confirmed: bool
    reason: str
    message: GmailMessageSummary | None = None


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


_RECEIPT_QUERY = (
    "newer_than:2d "
    "(from:ashbyhq.com OR from:greenhouse.io OR from:lever.co "
    "OR subject:application OR subject:applying OR subject:received OR subject:thank)"
)

_SUCCESS_PHRASES: tuple[str, ...] = (
    "thank you for applying",
    "thanks for applying",
    "thanks for taking the time to apply",
    "we received your application",
    "we've received your application",
    "we have received your application",
    "your application was received",
    "application received",
    "application was successfully submitted",
    "successfully submitted",
    "submitted your application",
    "your application for",
)

_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "senior",
    "staff",
    "software",
    "engineer",
    "engineering",
    "product",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _job_company_candidates(job: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("company", "company_name"):
        value = str(job.get(key) or "").strip()
        if value:
            candidates.append(value)
    site = str(job.get("site") or "").strip()
    if ":" in site:
        candidates.append(site.split(":", 1)[1].strip())
    elif site and site.lower() not in {"linkedin", "greenhouse", "lever", "ashby"}:
        candidates.append(site)

    for key in ("application_url", "url"):
        parsed = urlparse(str(job.get(key) or ""))
        host = parsed.netloc.lower()
        parts = [p for p in parsed.path.split("/") if p]
        if "ashbyhq.com" in host and parts:
            candidates.append(parts[0])
        elif "lever.co" in host and parts:
            candidates.append(parts[0])
        elif "greenhouse.io" in host and parts:
            candidates.append(parts[0])

    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        norm = _norm(candidate)
        if len(norm) >= 2 and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _job_title_terms(job: dict[str, Any]) -> set[str]:
    title = _norm(str(job.get("title") or ""))
    return {
        part
        for part in title.split()
        if len(part) >= 4 and part not in _STOPWORDS
    }


def _message_matches_receipt(job: dict[str, Any], message: GmailMessageSummary) -> bool:
    text = _norm(
        " ".join(
            [
                message.from_,
                message.subject,
                message.snippet,
            ]
        )
    )
    if not text:
        return False

    has_success_phrase = any(_norm(phrase) in text for phrase in _SUCCESS_PHRASES)
    if not has_success_phrase:
        return False

    companies = _job_company_candidates(job)
    if any(company in text for company in companies):
        return True

    title_terms = _job_title_terms(job)
    if title_terms:
        overlap = {term for term in title_terms if term in text}
        if len(overlap) >= min(2, len(title_terms)):
            return True

    return False


def search_messages(query: str, limit: int) -> list[GmailMessageSummary]:
    """Read-only Gmail search (metadata + snippet). Used by inbox recruiter-reply scan."""
    token = _access_token()
    response = httpx.get(
        f"{GMAIL_API}/users/me/messages",
        headers=_headers(token),
        params={"maxResults": max(1, min(limit, 20)), "q": query},
        timeout=30.0,
    )
    if response.status_code == 401:
        token = _refresh_access_token(_load_credentials())["access_token"]
        response = httpx.get(
            f"{GMAIL_API}/users/me/messages",
            headers=_headers(token),
            params={"maxResults": max(1, min(limit, 20)), "q": query},
            timeout=30.0,
        )
    response.raise_for_status()

    summaries: list[GmailMessageSummary] = []
    for item in (response.json().get("messages") or [])[:limit]:
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


def _search_messages(query: str, limit: int) -> list[GmailMessageSummary]:
    """Backward-compatible alias for apply receipt search and tests."""
    return search_messages(query, limit)


def search_application_receipt(
    job: dict[str, Any],
    *,
    limit: int = 20,
    query: str = _RECEIPT_QUERY,
) -> GmailReceiptResult:
    """Find a recent successful-application receipt for a submitted job."""
    try:
        messages = _search_messages(query, limit)
    except Exception as exc:
        return GmailReceiptResult(False, f"gmail_unavailable:{type(exc).__name__}: {exc}")

    for message in messages:
        if _message_matches_receipt(job, message):
            return GmailReceiptResult(True, "gmail_receipt_found", message)
    return GmailReceiptResult(False, "gmail_receipt_not_found")


def wait_for_application_receipt(
    job: dict[str, Any],
    *,
    timeout_seconds: int = 60,
    poll_seconds: int = 10,
) -> GmailReceiptResult:
    """Poll Gmail briefly after browser submit; only a matching receipt confirms apply."""
    deadline = time.time() + max(0, timeout_seconds)
    last = GmailReceiptResult(False, "gmail_receipt_not_checked")
    while True:
        last = search_application_receipt(job)
        if last.confirmed:
            return last
        if time.time() >= deadline:
            return last
        time.sleep(max(1, poll_seconds))
