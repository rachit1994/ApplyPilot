"""Y Combinator Work at a Startup deterministic adapter."""

from __future__ import annotations

from applypilot.apply.direct.adapters.base import Adapter

ADAPTER = Adapter(
    family="workatastartup",
    apply_button_texts=("apply", "apply now"),
    submit_button_texts=("send", "submit"),
    success_markers=(
        "message sent",
        "application sent",
        "application submitted",
        "your application has been sent",
    ),
    expired_markers=(
        "no longer accepting",
        "job is no longer available",
        "page not found",
        "404",
    ),
)
