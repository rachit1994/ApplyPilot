"""ATS family detection + provider fingerprint.

Shared by the LinkedIn URL resolver (stores the family), the Driver (picks an
adapter), the throttle gate (per-family caps), and apply_outcomes recording.

Two levels of identity:

  ats_family(url)        -- coarse vendor bucket from the host. Cheap, stable,
                            URL-only. "greenhouse", "lever", ..., or "unknown".

  provider_fingerprint() -- ats_family + a DOM signature hash. Finer identity
                            for the v2 learning loop so a vendor's DOM redesign
                            reads as a new variant instead of corrupting the old
                            profile. URL-only callers can omit the DOM part.

         host                          family
   ┌──────────────────────────┐  ┌──────────────────┐
   │ boards.greenhouse.io      │→ │ greenhouse       │
   │ grnh.se                   │→ │ greenhouse       │
   │ jobs.lever.co             │→ │ lever            │
   │ jobs.ashbyhq.com          │→ │ ashby            │
   │ *.myworkdayjobs.com       │→ │ workday          │
   │ (anything else)           │→ │ unknown          │
   └──────────────────────────┘  └──────────────────┘
"""

from __future__ import annotations

from hashlib import sha1
from urllib.parse import parse_qs, urlsplit

# Canonical family -> ordered host fragments that map to it. Order matters only
# for readability; matching is membership, not precedence (families are
# disjoint by host). Keep greenhouse's grnh.se short-link alias here so
# LinkedIn "Apply" redirects resolve to the right family.
_FAMILY_HOST_FRAGMENTS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("boards.greenhouse.io", "greenhouse.io", "grnh.se"),
    "lever": ("jobs.lever.co", "lever.co"),
    "ashby": ("jobs.ashbyhq.com", "ashbyhq.com"),
    "workday": ("myworkdayjobs.com", "workday.com"),
    "icims": ("icims.com",),
    "smartrecruiters": ("smartrecruiters.com",),
    "jobvite": ("jobvite.com",),
    "bamboohr": ("bamboohr.com",),
    "recruitee": ("recruitee.com",),
    "teamtailor": ("teamtailor.com",),
    "breezy": ("breezy.hr",),
    "workable": ("workable.com",),
    "taleo": ("taleo.net",),
    "successfactors": ("successfactors.com",),
    "rippling": ("rippling.com",),
    "paylocity": ("paylocity.com",),
    "workatastartup": ("workatastartup.com",),
}

# Families with a hand-written deterministic adapter (Phase B/C). Jobs on a
# family NOT in this set fall through to Claude rescue or get marked manual.
ADAPTER_FAMILIES: frozenset[str] = frozenset(
    {"greenhouse", "lever", "ashby", "workday"}
)

UNKNOWN_FAMILY = "unknown"

# Query-param signals that reveal the backing ATS even on a custom career
# domain (e.g. stripe.com/jobs?gh_jid=... is Greenhouse-backed, not "unknown").
# These are author-set by the ATS's own apply widget and are reliable.
_FAMILY_QUERY_PARAMS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("gh_jid", "gh_src"),
    "lever": ("lever-source", "lever_source"),
}


def ats_family(url: str | None) -> str:
    """Return the canonical ATS family for a URL, or 'unknown'.

    Two signals, host first:
      1. Host fragment (boards.greenhouse.io, jobs.lever.co, ...). Path is
         ignored on purpose: a landing page that merely links to Greenhouse
         should not be classified as Greenhouse.
      2. Query param (gh_jid, lever-source, ...). Many employers embed an ATS
         on their own careers domain; the ATS widget stamps a telltale param.
         This is what catches stripe.com/jobs?gh_jid=... -> greenhouse.
    """
    if not url:
        return UNKNOWN_FAMILY
    parts = urlsplit(str(url).strip())
    netloc = parts.netloc.lower()
    if not netloc:
        # Fall back to substring scan for bare hosts / odd inputs.
        netloc = str(url).strip().lower()
    for family, fragments in _FAMILY_HOST_FRAGMENTS.items():
        if any(fragment in netloc for fragment in fragments):
            return family
    # No host match — check query-param signals on custom career domains.
    if parts.query:
        params = parse_qs(parts.query)
        for family, keys in _FAMILY_QUERY_PARAMS.items():
            if any(k in params for k in keys):
                return family
    return UNKNOWN_FAMILY


def has_adapter(family: str | None) -> bool:
    """True when a deterministic adapter exists for this family."""
    return bool(family) and family in ADAPTER_FAMILIES


def apex_domain(url: str | None) -> str:
    """Return a coarse apex domain for per-company throttling.

    Not a public-suffix-list parse (that would add a dependency); a pragmatic
    "last two labels" heuristic, which is correct for the .com/.io/.co hosts
    that dominate ATS traffic. Used only for the per-apex-domain daily cap, so
    occasional over-grouping on multi-label TLDs is acceptable and safe (it
    throttles slightly more, never less).
    """
    if not url:
        return ""
    netloc = urlsplit(str(url).strip()).netloc.lower()
    if not netloc:
        netloc = str(url).strip().lower()
    host = netloc.split("@")[-1].split(":")[0]
    labels = [p for p in host.split(".") if p]
    if len(labels) <= 2:
        return ".".join(labels)
    return ".".join(labels[-2:])


def provider_fingerprint(url: str | None, dom_signature: str | None = None) -> str:
    """Stable provider identity: '<family>:<8-hex DOM-sig>' or '<family>:url'.

    With no DOM signature (URL-only callers like the resolver) the fingerprint
    is '<family>:url' — coarse but stable. The Driver passes a DOM signature
    (a hash of field-name conventions) so the v2 learner can tell variants
    apart. Same inputs always produce the same fingerprint.
    """
    family = ats_family(url)
    if dom_signature:
        digest = sha1(dom_signature.encode("utf-8")).hexdigest()[:8]
        return f"{family}:{digest}"
    return f"{family}:url"
