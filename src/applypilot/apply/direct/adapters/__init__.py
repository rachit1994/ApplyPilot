"""Per-ATS deterministic adapters (Phase B/C).

Each adapter maps profile/resolver answers to a specific ATS's stable DOM with
zero LLM tokens. Dispatch is by fingerprint.ats_family:

    greenhouse.py  -- boards.greenhouse.io           (Phase B)
    lever.py       -- jobs.lever.co                   (Phase B)
    ashby.py       -- jobs.ashbyhq.com                (Phase B)
    workday.py     -- *.myworkdayjobs.com             (Phase C)

Jobs on a family without an adapter fall through to Claude rescue or are
marked manual. See docs/maxed-apply-pipeline-jun-2026.md §4.
"""

from __future__ import annotations

from applypilot.apply import apply_settings
from applypilot.apply.direct.adapters.base import Adapter
from applypilot.apply.direct.adapters import ashby, greenhouse, lever, workatastartup

# family -> descriptor. Only families whose deterministic form-fill is verified
# end-to-end are dispatched to the Driver; everything else escalates to the
# Claude rescue path (which handles any form), so an unverified ATS never hangs
# or mis-fills. Greenhouse is confirmed (real submit, $0). Lever/Ashby use a
# different DOM for custom questions and are staged here but NOT yet dispatched
# pending their own field-handling + fixtures; flip them on once verified.
_REGISTRY: dict[str, Adapter] = {
    greenhouse.ADAPTER.family: greenhouse.ADAPTER,
    lever.ADAPTER.family: lever.ADAPTER,
    ashby.ADAPTER.family: ashby.ADAPTER,
    workatastartup.ADAPTER.family: workatastartup.ADAPTER,
}

# Reserved for families not yet verified end-to-end.
_STAGED: dict[str, Adapter] = {}


def get_adapter(family: str | None) -> Adapter | None:
    """Return the deterministic adapter for an ATS family, or None to escalate."""
    if not family:
        return None
    if family in apply_settings.direct_excluded_families():
        return None
    return _REGISTRY.get(family)


__all__ = ["Adapter", "get_adapter"]
