"""Read-only structural selector self-healing for replay/fill locators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def xpath_literal(s: str) -> str:
    """Quote a string for use as an XPath literal (handles embedded quotes)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat('" + "',\"'\",'".join(parts) + "')"


def _try_locator(page, getter: Callable[[], Any]):
    try:
        loc = getter()
        if loc is not None and loc.count() > 0:
            return loc
    except Exception:  # noqa: BLE001
        pass
    return None


def _nearby_label_locator(page, descriptor: dict):
    label = (descriptor.get("label") or descriptor.get("nearby_text") or "").strip()
    name_attr = (descriptor.get("name_attr") or descriptor.get("name") or "").strip()
    tag = (descriptor.get("tag") or "input").strip() or "input"
    field_type = (descriptor.get("type") or "").strip()

    if label:
        for exact in (False, True):
            loc = _try_locator(
                page,
                lambda e=exact: page.get_by_label(label, exact=e).first,
            )
            if loc is not None:
                return loc

    if name_attr:
        selectors = (
            f'{tag}[name="{name_attr}"]',
            f'[name="{name_attr}"]',
            f'#{name_attr}',
            f'[id="{name_attr}"]',
        )
        if field_type:
            selectors = (f'{tag}[type="{field_type}"][name="{name_attr}"]',) + selectors
        for sel in selectors:
            loc = _try_locator(page, lambda s=sel: page.locator(s).first)
            if loc is not None:
                return loc

    return None


def heal_locator(page, descriptor: dict | None):
    """Find an element using structural fallbacks.

    descriptor keys (any subset): role, name, label, nearby_text, css, tag,
    text, name_attr, type.

    Try in order: exact css → text (button/link roles) → role+name → text →
    xpath normalize-space → nearby-label proximity.

    Returns a Playwright Locator or None. Read-only — never clicks or submits.
    """
    descriptor = descriptor or {}
    css = (descriptor.get("css") or "").strip()
    if css:
        loc = _try_locator(page, lambda: page.locator(css).first)
        if loc is not None:
            return loc

    text = (descriptor.get("text") or "").strip()
    role = (descriptor.get("role") or "").strip()
    name = (
        (descriptor.get("name") or "").strip()
        or text
        or (descriptor.get("label") or "").strip()
    )

    if text and not role:
        for r in ("button", "link"):
            loc = _try_locator(
                page,
                lambda role_name=r, n=text: page.get_by_role(
                    role_name, name=n, exact=False
                ).first,
            )
            if loc is not None:
                return loc

    if role and name:
        loc = _try_locator(
            page,
            lambda: page.get_by_role(role, name=name, exact=False).first,
        )
        if loc is not None:
            return loc

    if text:
        loc = _try_locator(page, lambda: page.get_by_text(text, exact=False).first)
        if loc is not None:
            return loc

        loc = _try_locator(
            page,
            lambda: page.locator(
                f"xpath=//*[normalize-space(.)={xpath_literal(text)}]"
            ).last,
        )
        if loc is not None:
            return loc

    return _nearby_label_locator(page, descriptor)
