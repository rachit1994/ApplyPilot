"""Deterministic keyword extraction for template tailoring (no LLM)."""

from __future__ import annotations

import re
from collections import Counter

_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does for from had has
    have he her hers him his how i if in into is it its just me more most my no not
    of on or our out over s she so some such than that the their them then there
    these they this those through to too up us was we were what when where which
    while who will with would you your
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def extract_top_keywords(text: str, top_n: int = 15) -> list[str]:
    """Return the most frequent meaningful tokens in *text* (case-preserved first seen)."""
    if not text or top_n <= 0:
        return []

    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for match in _TOKEN_RE.finditer(text):
        raw = match.group(0)
        key = raw.lower()
        if len(key) < 3 or key in _STOPWORDS:
            continue
        counts[key] += 1
        first_seen.setdefault(key, raw)

    ranked = sorted(counts.keys(), key=lambda k: (-counts[k], first_seen[k].lower()))
    return [first_seen[k] for k in ranked[:top_n]]


def keyword_overlap_ratio(
    resume_text: str,
    job_description: str,
    top_n: int = 15,
) -> float:
    """Fraction of top job keywords found in *resume_text* (case-insensitive)."""
    job_keywords = extract_top_keywords(job_description, top_n=top_n)
    if not job_keywords:
        return 1.0

    resume_lower = resume_text.lower()
    matched = sum(1 for kw in job_keywords if kw.lower() in resume_lower)
    return matched / len(job_keywords)
