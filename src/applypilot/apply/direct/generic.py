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

GENERIC_FAMILY = "generic"

ADAPTER = Adapter(
    family=GENERIC_FAMILY,
    apply_button_texts=(
        "apply", "apply now", "apply for this job", "apply for this role",
        "i'm interested", "i am interested", "apply on company site",
        "apply for this position", "submit application", "start application",
    ),
    submit_button_texts=(
        "submit application", "submit", "send application", "apply",
        "submit my application", "finish", "send",
    ),
    success_markers=(
        "thank you for applying",
        "application received",
        "application has been received",
        "we have received your application",
        "your application has been submitted",
        "successfully submitted",
        "application submitted",
        "thanks for applying",
        "thank you for your application",
        "thank you for your interest",
    ),
    expired_markers=(
        "no longer accepting",
        "position has been filled",
        "this job is no longer",
        "job not found",
        "page not found",
        "404",
        "applications are closed",
    ),
)


def generic_form_enabled() -> bool:
    """Attempt unknown forms with the generic adapter (default on)."""
    raw = os.environ.get("APPLYPILOT_DIRECT_GENERIC")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")
