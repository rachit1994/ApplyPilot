"""Lever adapter — jobs.lever.co.

Lever's posting page has an "Apply for this job" button that routes to
/<company>/<id>/apply with the form; submit reads "Submit application".
Success redirects to a "/thanks" page / shows an application-received message.
"""

from __future__ import annotations

from applypilot.apply.direct.adapters.base import Adapter

ADAPTER = Adapter(
    family="lever",
    apply_button_texts=("apply for this job", "apply", "apply now"),
    submit_button_texts=("submit application", "submit"),
    success_markers=(
        "thank you",
        "application has been submitted",
        "your application has been received",
        "we received your application",
    ),
    expired_markers=(
        "no longer accepting",
        "position is no longer",
        "page not found",
        "404",
    ),
)
