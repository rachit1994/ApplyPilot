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
