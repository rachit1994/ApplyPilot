"""Generic deterministic adapter for unknown providers.

Most India employer/career forms aren't Greenhouse/Lever/Ashby — they're plain
company forms or Indian ATS (Keka, Darwinbox, Zoho Recruit, Freshteam, greytHR).
The Driver's extract→resolve→fill→verify pipeline is generic; only the per-vendor
"chrome" (apply/submit/success/expired markers) differs. This generic adapter
supplies broad, safe markers so the Driver can ATTEMPT any navigated form and
still submit only on full confidence (it parks on uncertainty — never junk).

Enabled by default; disable with APPLYPILOT_DIRECT_GENERIC=0.
"""

from __future__ import annotations

import os

from applypilot.apply.direct.adapters.base import Adapter
from applypilot.apply.direct.generic_defaults import (
    GENERIC_APPLY_BUTTON_TEXTS,
    GENERIC_EXPIRED_MARKERS,
    GENERIC_FAMILY,
    GENERIC_SUBMIT_BUTTON_TEXTS,
    GENERIC_SUCCESS_MARKERS,
)

ADAPTER = Adapter(
    family=GENERIC_FAMILY,
    apply_button_texts=GENERIC_APPLY_BUTTON_TEXTS,
    submit_button_texts=GENERIC_SUBMIT_BUTTON_TEXTS,
    success_markers=GENERIC_SUCCESS_MARKERS,
    expired_markers=GENERIC_EXPIRED_MARKERS,
)


def generic_form_enabled() -> bool:
    """Attempt unknown forms with the generic adapter (default on)."""
    raw = os.environ.get("APPLYPILOT_DIRECT_GENERIC")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")
