"""Greenhouse adapter — boards.greenhouse.io / job-boards.greenhouse.io.

Greenhouse renders the application form inline on the job page (no reveal click
needed on the modern job-boards host); the submit control reads "Submit
Application". Success shows a "Thank you for applying" confirmation.
"""

from __future__ import annotations

from applypilot.apply.direct.adapters.base import Adapter

ADAPTER = Adapter(
    family="greenhouse",
    apply_button_texts=("apply", "apply for this job", "apply now"),
    submit_button_texts=("submit application", "submit"),
    success_markers=(
        "thank you for applying",
        "your application has been submitted",
        "application has been received",
        "thanks for applying",
    ),
    expired_markers=(
        "no longer accepting applications",
        "position has been filled",
        "page not found",
        "404",
    ),
)
