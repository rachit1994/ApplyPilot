"""HTTP client for the OpenOutreach REST API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class OpenOutreachError(Exception):
    """Base error for OpenOutreach API failures."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class OpenOutreachClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            response = client.request(method, url, json=json, params=params)
        if response.status_code >= 400:
            body: dict = {}
            try:
                body = response.json()
            except Exception:
                body = {"detail": response.text}
            detail = body.get("detail", response.text)
            code = body.get("code")
            raise OpenOutreachError(str(detail), status_code=response.status_code, code=code)
        if response.status_code == 204:
            return None
        return response.json()

    def health(self) -> dict:
        return self._request("GET", "/health")

    def status(self) -> dict:
        return self._request("GET", "/status")

    def list_deals(
        self,
        *,
        campaign: str | None = None,
        state: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if campaign:
            params["campaign"] = campaign
        if state:
            params["state"] = state
        return self._request("GET", "/deals", params=params)

    def connect(
        self,
        public_id: str,
        *,
        campaign: str | None = None,
        wait: bool = True,
        timeout: float = 120.0,
    ) -> dict:
        body: dict[str, Any] = {"public_id": public_id}
        if campaign:
            body["campaign"] = campaign
        params = {"wait": "true" if wait else "false", "timeout": timeout}
        return self._request("POST", "/actions/connect", json=body, params=params)

    def message(
        self,
        public_id: str,
        message: str,
        *,
        campaign: str | None = None,
        conversation_urn: str | None = None,
        via: str = "auto",
        wait: bool = True,
        timeout: float = 120.0,
    ) -> dict:
        body: dict[str, Any] = {"public_id": public_id, "message": message, "via": via}
        if campaign:
            body["campaign"] = campaign
        if conversation_urn:
            body["conversation_urn"] = conversation_urn
        params = {"wait": "true" if wait else "false", "timeout": timeout}
        return self._request("POST", "/actions/message", json=body, params=params)

    def scrape_profile(
        self,
        public_id: str,
        *,
        campaign: str | None = None,
        wait: bool = True,
    ) -> dict:
        body: dict[str, Any] = {"public_id": public_id}
        if campaign:
            body["campaign"] = campaign
        params = {"wait": "true" if wait else "false"}
        return self._request("POST", "/actions/scrape-profile", json=body, params=params)

    def sync_inbox(
        self,
        *,
        since_days: int = 14,
        limit: int = 50,
        include_messages: bool = True,
        use_browser: bool = True,
        scroll_passes: int | None = None,
        max_pages: int | None = None,
        wait: bool = True,
        timeout: float = 300.0,
    ) -> dict:
        body: dict[str, Any] = {
            "since_days": since_days,
            "limit": limit,
            "include_messages": include_messages,
            "use_browser": use_browser,
        }
        if scroll_passes is not None:
            body["scroll_passes"] = scroll_passes
        if max_pages is not None:
            body["max_pages"] = max_pages
        params = {"wait": "true" if wait else "false", "timeout": timeout}
        result = self._request("POST", "/actions/sync-inbox", json=body, params=params)
        if isinstance(result, dict) and "result" in result and "threads" not in result:
            inner = result.get("result")
            if isinstance(inner, dict):
                return inner
        return result if isinstance(result, dict) else {}


def check_openoutreach_health(base_url: str, api_key: str) -> tuple[bool, str]:
    """Return (ok, detail) for doctor / startup checks."""
    if not api_key:
        return False, "OPENOUTREACH_API_KEY not set"
    try:
        client = OpenOutreachClient(base_url, api_key, timeout=15.0)
        body = client.health()
        if body.get("ok") and body.get("onboarded"):
            return True, f"{base_url} (onboarded)"
        if body.get("ok"):
            return False, f"{base_url} reachable but LinkedIn not onboarded"
        return False, f"health check failed: {body}"
    except OpenOutreachError as exc:
        return False, str(exc)
    except httpx.HTTPError as exc:
        return False, f"cannot reach OpenOutreach: {exc}"
