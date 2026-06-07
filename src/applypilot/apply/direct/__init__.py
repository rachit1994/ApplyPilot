"""Direct Apply: deterministic Playwright form-fill, no LLM in the hot loop.

See docs/maxed-apply-pipeline-jun-2026.md for the architecture and ceiling math.

Layering (no import cycles):

    fingerprint.py   -- URL/DOM -> canonical ATS family + provider fingerprint
        ^
    qa_bank.py       -- Resolver Tier-1 answer cache
        ^
    (adapters, resolver, driver -- Phase B/C, added on top)

This package is inert until `APPLYPILOT_APPLY_ENGINE=direct`; the existing
Claude apply path in launcher.run_job stays the default and the rescue tier.
"""
