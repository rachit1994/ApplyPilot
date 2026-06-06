"""Ashby adapter — jobs.ashbyhq.com.

Ashby shows the JD with an "Apply for this job"/"Apply" button that reveals the
application form; submit reads "Submit Application". Success renders a "Success"
heading with "Thank you for your interest in <company>".
"""

from __future__ import annotations

from applypilot.apply.direct.adapters.base import Adapter

ADAPTER = Adapter(
    family="ashby",
    apply_button_texts=("apply for this job", "apply", "apply now"),
    submit_button_texts=("submit application", "submit"),
    success_markers=(
        "thank you for your interest",
        "application has been received",
        "your application has been submitted",
        "successfully submitted",
    ),
    expired_markers=(
        "no longer accepting",
        "this job is no longer",
        "page not found",
        "not found",
        "404",
    ),
)
