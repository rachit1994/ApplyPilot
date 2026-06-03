"""Adapter descriptor: the small bundle of per-ATS DOM knowledge the Driver needs.

The form *fill* is generic — the extractor stamps every fillable field with a
stable locator and the resolver answers them, so the Driver fills any ATS the
same way. What differs per vendor is only the chrome around the form:

    apply_button_texts -- text on the button that reveals the form, when the
                          landing page shows the JD first (click it, re-extract)
    submit_button_texts-- text on the final submit control
    success_markers    -- body-text substrings that confirm a real submission
    expired_markers    -- body-text substrings meaning the posting is gone

Everything is data; the Driver does the driving. A vendor without a descriptor
falls through to Claude rescue (see fingerprint.ADAPTER_FAMILIES).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field


@dataclass(frozen=True)
class Adapter:
    family: str
    apply_button_texts: tuple[str, ...] = dc_field(default_factory=tuple)
    submit_button_texts: tuple[str, ...] = ("submit application", "submit")
    success_markers: tuple[str, ...] = (
        "thank you for",
        "application has been received",
        "application was submitted",
        "successfully submitted",
        "we have received your application",
    )
    expired_markers: tuple[str, ...] = (
        "no longer accepting",
        "position has been filled",
        "job is no longer",
        "page not found",
        "404",
    )
