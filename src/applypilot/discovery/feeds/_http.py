"""Shared HTTP helpers for feed ingests."""

from __future__ import annotations

import httpx

DEFAULT_HEADERS = {
    "User-Agent": "ApplyPilot/0.3 (+local job discovery)",
    "Accept": "application/json, text/xml, */*",
}


def get_json(url: str, *, timeout: float = 30.0) -> object:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def get_text(url: str, *, timeout: float = 30.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text
