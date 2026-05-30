"""Measurable before/after prompt sizes: legacy slim vs playbook mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from applypilot import config
from applypilot.apply import apply_settings, prompt as prompt_mod
from applypilot.apply.worker_playbook import build_worker_apply_prompt

from test_apply_quota_e2e import _build_prompt_with_slim, _job_for, _minimal_profile

GREENHOUSE_URL = "https://boards.greenhouse.io/acme/jobs/123"


def _write_benchmark_doc(legacy_len: int, playbook_len: int) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out = repo_root / "docs/superpowers/specs/2026-05-29-worker-apply-playbook-benchmark.md"
    delta_pct = (1.0 - playbook_len / legacy_len) * 100.0 if legacy_len else 0.0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"""# Worker apply playbook benchmark

Measured in CI via `tests/test_worker_playbook_benchmark.py` on a greenhouse fixture job with minimal profile (`APPLYPILOT_DIR` isolated in test).

| Metric | Legacy slim | Playbook | Delta |
|--------|-------------|----------|-------|
| Prompt chars | {legacy_len:,} | {playbook_len:,} | {delta_pct:.1f}% smaller |

## Mocked apply outcomes (fixture)

| Mode | Terminal line | Resolved status |
|------|---------------|-----------------|
| Playbook | `RESULT:applied` | `submitted_unverified:playbook_applied` |
| Playbook | `RESULT:failed:stuck` | `failed:stuck` |
| Legacy | `RESULT:APPLIED` (no JSON) | `submitted_unverified:legacy RESULT:APPLIED without structured proof` |

## Default flag

`APPLYPILOT_APPLY_PROMPT_MODE` defaults to `legacy`. Use `playbook` for the worker doc-only prompt:

```bash
export APPLYPILOT_APPLY_PROMPT_MODE=playbook
# or: applypilot apply --prompt-mode playbook ...
```

## Notes

- Playbook mode does not mandate `RESULT_JSON`; verification tier still treats bare `RESULT:applied` as unverified submit.
- Turn/cost deltas require live or mocked `run_job` stream-json runs on the same fixture set (not repeated here).
""",
        encoding="utf-8",
    )


def _measure_legacy_slim(job: dict, monkeypatch: pytest.MonkeyPatch) -> int:
    return len(_build_prompt_with_slim(job, slim=True, monkeypatch=monkeypatch))


def _measure_playbook(job: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "APPLY_WORKER_DIR", tmp_path / "workers")
    monkeypatch.setattr(config, "load_profile", lambda: _minimal_profile())

    def fake_ensure_resume_pdf(path: str | Path) -> Path:
        pdf = Path(path)
        if pdf.suffix.lower() != ".pdf":
            pdf = pdf.with_suffix(".pdf")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        if not pdf.exists():
            pdf.write_bytes(b"%PDF-1.4\n")
        return pdf.resolve()

    monkeypatch.setattr(prompt_mod, "ensure_resume_pdf", fake_ensure_resume_pdf)
    text = build_worker_apply_prompt(job, upload_dir=tmp_path / "w0")
    return len(text)


def test_benchmark_playbook_prompt_smaller_than_legacy_slim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Playbook mode should be materially smaller than legacy slim on greenhouse fixture."""
    job = _job_for(GREENHOUSE_URL, tmp_path)
    legacy_len = _measure_legacy_slim(job, monkeypatch)
    playbook_len = _measure_playbook(job, tmp_path, monkeypatch)

    global BASELINE_LEGACY_SLIM_CHARS, BASELINE_PLAYBOOK_CHARS
    BASELINE_LEGACY_SLIM_CHARS = legacy_len
    BASELINE_PLAYBOOK_CHARS = playbook_len

    savings = 1.0 - (playbook_len / legacy_len)
    assert playbook_len < legacy_len, (
        f"expected playbook ({playbook_len}) < legacy slim ({legacy_len})"
    )
    assert savings >= 0.30, (
        f"expected >=30% prompt reduction, got {savings:.1%} "
        f"(legacy={legacy_len}, playbook={playbook_len})"
    )

    _write_benchmark_doc(legacy_len, playbook_len)


def test_benchmark_fixture_outcome_playbook_applied(tmp_path: Path):
    """Document expected parsed outcome for playbook RESULT:applied (no RESULT_JSON)."""
    from applypilot.apply.playbook_results import resolve_playbook_result

    assert (
        resolve_playbook_result("RESULT:applied\n")
        == "submitted_unverified:playbook_applied"
    )


