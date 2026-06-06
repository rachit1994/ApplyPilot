"""Workable deterministic adapter.

Workable forms are plain enough for the generic extract/resolve/fill pipeline;
this adapter supplies the family identity so deterministic-only routing does
not park them before the Driver gets a chance to fill the form.
"""

from __future__ import annotations

from applypilot.apply.direct.adapters.base import Adapter
from applypilot.apply.direct.generic import ADAPTER as GENERIC_ADAPTER

ADAPTER = Adapter(
    family="workable",
    apply_button_texts=GENERIC_ADAPTER.apply_button_texts,
    submit_button_texts=GENERIC_ADAPTER.submit_button_texts,
    success_markers=GENERIC_ADAPTER.success_markers
    + (
        "your application was sent",
        "application sent",
    ),
    expired_markers=GENERIC_ADAPTER.expired_markers,
)
