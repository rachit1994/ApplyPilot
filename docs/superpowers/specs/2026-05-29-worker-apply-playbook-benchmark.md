# Worker apply playbook benchmark

Measured in CI via `tests/test_worker_playbook_benchmark.py` on a greenhouse fixture job with minimal profile (`APPLYPILOT_DIR` isolated in test).

| Metric | Legacy slim | Playbook | Delta |
|--------|-------------|----------|-------|
| Prompt chars | 15,991 | 10,575 | 33.9% smaller |

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
