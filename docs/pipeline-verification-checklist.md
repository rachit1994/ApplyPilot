# ApplyPilot Pipeline Verification Checklist

Use this checklist before calling a pipeline/apply change done. It is intentionally concrete: every item needs either a passing test, a DB row, a log line, or an explicit external blocker.

## Run Every Time

1. Run the focused tests for the touched area.
2. Run the full test suite: `uv run pytest`.
3. Run an isolated dry pipeline with a temp DB:
   `APPLYPILOT_DIR=$(mktemp -d) LLM_URL=http://127.0.0.1:9/v1 python -m applypilot run --dry-run --workers 1 --validation lenient`
4. Run the read-only checklist against the real local DB:
   `applypilot debug verification-checklist --month YYYY-MM`
5. If auto-apply was touched, run a visible dry apply first:
   `applypilot apply --dry-run --watch --limit 1 --min-score 0`

## What Must Be Covered

| Area | Positive evidence |
| --- | --- |
| Gemini usage and bill trend | `llm_usage_events` has rows by provider/model/operation, and `applypilot llm-usage --month YYYY-MM` shows call counts and estimated USD. Provider invoice is still the billing source of truth. |
| Claude Code quota reset | Quota failures store a full ISO `apply_not_before`; `datetime(apply_not_before)` is parseable; future rows are parked; expired rows become acquirable again. |
| Naukri and Wellfound apply routing | Queue ordering prioritizes Naukri, then Wellfound, then ATS boards; ready counts are visible in `applypilot debug verification-checklist`. |
| Google SSO | The apply prompt may use Google SSO only when the browser is already logged in and can click a safe "Continue as" flow; password/passkey/MFA still pauses/fails safely. |
| Gmail verification codes | `applypilot gmail status` succeeds; apply logs include `verification_code_used` when a code is used; the Applications view can display the parsed verification evidence. |
| Application proof | Successful applies require structured `RESULT_JSON` plus Python-side verification. Otherwise rows become `submitted_unverified`, not `applied`. |
| Templates and Gemini reduction | Template files exist under `~/.applypilot/templates`; B-grade jobs use archetype templates where available, while A-grade jobs can still call the LLM. |
| Docs parity | Any doc that says a feature is implemented must name the command/test/DB evidence that proves it. |

## Known External Blockers

- Real application submission is a live side effect. Do not submit to real jobs unless the user explicitly asks for live submission in the current message.
- Google account login with password, passkey, or MFA cannot be fully automated safely. The supported path is an already-authenticated Chrome profile or a safe "Continue as" SSO button.
- Provider billing totals are not derivable from local code alone. ApplyPilot records local token/cost estimates; actual monthly charges must be checked in provider billing email/dashboard.
