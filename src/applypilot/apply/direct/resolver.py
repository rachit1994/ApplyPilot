"""The Resolver — answer intelligence in tiers.

Given the extractor's list of fillable fields, return {field_key: answer} for
everything that can be answered, plus the set of fields that could not be
resolved (the Driver escalates the whole job to Claude rescue if any REQUIRED
field is unresolved).

    Tier 0  profile_binding rules   ~70% of fields   $0
    Tier 1  qa_bank cache           most screening   $0 (after warm-up)
    Tier 2  Gemini batch resolve    novel forms      ~$0.001 / form (one call)

First hit wins. Tier 2 sends ONE Gemini call for ALL of a form's leftover
fields (not one per field), keyed by the field's stable `key`, and writes every
answer back to the Q&A bank so the bank self-warms. select/radio answers are
snapped to a real option via profile_binding.choose_select_option.

    fields ──► Tier 0 ─miss─► Tier 1 ─miss─► collect ──► Tier 2 (1 batch call)
                 │hit            │hit                         │
                 ▼               ▼                            ▼
              answers         answers                  answers + writeback
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field as dc_field

from applypilot.apply.direct import profile_binding, qa_bank
from applypilot.apply.direct.profile_binding import Field

logger = logging.getLogger(__name__)


@dataclass
class ResolveOutcome:
    """Result of resolving a whole form."""

    answers: dict[str, str] = dc_field(default_factory=dict)   # field.key -> answer
    via: dict[str, str] = dc_field(default_factory=dict)       # field.key -> tier label
    unresolved: list[str] = dc_field(default_factory=list)     # field.keys with no answer
    unresolved_required: list[str] = dc_field(default_factory=list)
    tier_max: int = 0          # highest tier used (0..2)
    llm_field_count: int = 0   # fields answered by Tier 2

    def add(self, key: str, answer: str, tier: int, via: str) -> None:
        self.answers[key] = answer
        self.via[key] = via
        self.tier_max = max(self.tier_max, tier)


def _user_override(label: str, conn) -> str | None:
    """User correction for this field label, if any (best-effort, never raises)."""
    try:
        from applypilot.database import get_field_override

        return get_field_override(label, conn)
    except Exception:  # noqa: BLE001
        return None


def _field_key(field: Field) -> str:
    """Stable per-field identity for the answers map (extractor supplies one;
    fall back to a label+name composite when absent)."""
    key = getattr(field, "key", None)
    if key:
        return str(key)
    return f"{profile_binding._norm(field.label)}|{profile_binding._norm(field.name_attr)}"


# Labels that carry no disambiguating signal. Their qa_bank key collapses onto
# every other nameless field, so one stored answer leaks everywhere (this is how
# a phone number got served to random "text" inputs). Never cache or serve them.
_WEAK_LABELS: frozenset[str] = frozenset(
    {"", "text", "field", "search", "select", "select...", "untitled"}
)
_DIAL_CODE_RE = __import__("re").compile(r"\+\d")


def _weak_label(field: Field) -> bool:
    from applypilot.apply.direct.qa_bank import normalize_text

    return normalize_text(field.label) in _WEAK_LABELS


def _cacheable(field: Field, answer: str) -> bool:
    """A select answer that is a phone dial code (e.g. 'Norfolk Island +672') is
    a country-picker artifact, never a real screening answer — don't cache it."""
    if _weak_label(field):
        return False
    if _answer_type(field) == "select" and _DIAL_CODE_RE.search(answer or ""):
        return False
    return True


def _snap_to_option(field: Field, answer: str) -> str | None:
    """For select/radio fields, map the answer to a real option (or None)."""
    if field.options:
        return profile_binding.choose_select_option(answer, field.options)
    return answer


def resolve(
    fields: list[Field],
    tokens: dict,
    *,
    job: dict | None = None,
    conn=None,
    gemini_enabled: bool = True,
) -> ResolveOutcome:
    """Resolve every fillable field through the tiers. Pure of any browser."""
    out = ResolveOutcome()
    leftovers: list[Field] = []

    for f in fields:
        key = _field_key(f)

        # Tier -1 — user correction. A value the user fixed once wins over
        # rules, cache, and the LLM, on this field for every future form.
        override = _user_override(f.label, conn)
        if override is not None:
            snapped = _snap_to_option(f, override)
            if snapped is not None:
                out.add(key, snapped, 0, "override:user")
                continue

        # Tier 0 — deterministic rules.
        r = profile_binding.resolve_field(f, tokens)
        if r is not None:
            snapped = _snap_to_option(f, r.answer)
            if snapped is not None:
                out.add(key, snapped, 0, f"t0:{r.via}")
                continue

        # Tier 1 — Q&A bank cache. Skip weak/anonymous labels: their key
        # collapses onto unrelated fields and would serve a stale wrong answer.
        cached = None
        if not _weak_label(f):
            cached = qa_bank.lookup(
                f.label,
                section_header=f.section_header,
                name_attr=f.name_attr,
                answer_type=_answer_type(f),
                conn=conn,
            )
        if cached is not None:
            snapped = _snap_to_option(f, cached)
            if snapped is not None:
                out.add(key, snapped, 1, "t1:cache")
                continue

        leftovers.append(f)

    # Resolve every visible leftover field, including optional fields. Optional
    # blanks submit on many ATSes, but they also make the filled application look
    # careless and hide useful signals from the dashboard review log.
    billable = list(leftovers)

    if billable and gemini_enabled:
        try:
            batch = _gemini_batch(billable, tokens, job or {})
        except Exception as exc:  # noqa: BLE001 - resolver must not crash the apply
            logger.warning("Tier-2 Gemini resolve failed: %s", exc)
            batch = {}
        for f in billable:
            key = _field_key(f)
            ans = batch.get(key)
            if ans:
                snapped = _snap_to_option(f, ans)
                if snapped is not None:
                    out.add(key, snapped, 2, "t2:gemini")
                    out.llm_field_count += 1
                    _writeback(f, snapped, conn)
                    continue
            _mark_unresolved(out, f)
    else:
        for f in billable:
            _mark_unresolved(out, f)

    return out


def _mark_unresolved(out: ResolveOutcome, f: Field) -> None:
    key = _field_key(f)
    out.unresolved.append(key)
    if f.required:
        out.unresolved_required.append(key)


def _answer_type(f: Field) -> str:
    if f.tag == "select" or f.options:
        return "select"
    if f.type in ("checkbox", "radio"):
        return "bool"
    if f.type == "number":
        return "number"
    return "text"


def _writeback(f: Field, answer: str, conn) -> None:
    if not _cacheable(f, answer):
        return
    try:
        qa_bank.store(
            f.label,
            answer,
            answer_type=_answer_type(f),
            section_header=f.section_header,
            name_attr=f.name_attr,
            scope="generic",
            source="gemini",
            conn=conn,
        )
    except Exception:  # noqa: BLE001 - cache writeback is best-effort
        logger.debug("qa_bank writeback failed for %r", f.label, exc_info=True)


_GEMINI_PROMPT = """You are filling a job application form. Answer each field for \
this candidate. Return STRICT JSON mapping each field's "key" to a short answer \
string. For select fields, choose EXACTLY one of the provided options. For \
free-text, write 2-3 specific sentences. Do not invent facts not in the profile.

CANDIDATE PROFILE (JSON):
{profile}

JOB: {company} — {role}

FIELDS (JSON list):
{fields}

Return only JSON like {{"<key>": "<answer>", ...}}. No prose, no markdown."""


def _gemini_batch(fields: list[Field], tokens: dict, job: dict) -> dict[str, str]:
    """One Gemini call answering all leftover fields. Keyed by field.key."""
    from applypilot.database import record_llm_usage
    from applypilot.llm import get_client

    payload_fields = [
        {
            "key": _field_key(f),
            "label": f.label,
            "type": f.type or f.tag,
            "section": f.section_header,
            "options": list(f.options),
            "required": f.required,
        }
        for f in fields
    ]
    prompt = _GEMINI_PROMPT.format(
        profile=json.dumps(tokens, ensure_ascii=False),
        company=tokens.get("company") or job.get("company") or job.get("site") or "the company",
        role=job.get("title") or "this role",
        fields=json.dumps(payload_fields, ensure_ascii=False),
    )
    client = get_client()
    raw = client.ask(prompt)
    try:
        record_llm_usage(
            provider="gemini",
            model=getattr(client, "model", "gemini"),
            operation="apply_resolve",
            estimated=True,
            metadata={"fields": len(fields), "job_url": job.get("url")},
        )
    except Exception:  # noqa: BLE001
        logger.debug("record_llm_usage failed for resolver", exc_info=True)
    return _parse_json_answers(raw)


def _parse_json_answers(raw: str) -> dict[str, str]:
    """Extract the first JSON object from the model output, tolerating fences."""
    if not raw:
        return {}
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}
