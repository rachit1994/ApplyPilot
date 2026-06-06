# Indian Portal Apply — Recon & Status Report

Date: 2026-06-04. Task: stop applying on Greenhouse/Ashby; build deterministic
(no-Claude) apply for Indian portals, one portal at a time; if a portal is
completely blocked, move on and report.

---

## 1. What was changed (done + tested)

**Stopped applying on Greenhouse and Ashby.**
- `apply_settings._SKIP_ATS_FAMILIES_DEFAULT` → `"greenhouse,ashby"` (was `"greenhouse"`).
  This already drives discovery exclusion + direct-adapter exclusion.
- Added a single guard at the apply dispatch entry (`_run_job_with_optional_fallback`
  in `launcher.py`): any job whose apply URL resolves to an excluded ATS family is
  **parked as `needs_adapter` (reversible) and never escalates to Claude**, in every
  engine/mode.
- Override with `APPLYPILOT_SKIP_ATS_FAMILIES` (comma-separated; empty disables).
- Tests: greenhouse + ashby jobs park `excluded_ats:*` and `run_job` (Claude) is never
  called; cap/needs_adapter behavior preserved.

**"No Claude" is enforceable today** via `applypilot apply --deterministic-only`
(parks non-adapter jobs as `needs_adapter` instead of escalating). Use this mode.

---

## 2. The hard finding: India-native portals are login-walled

The deterministic engine (`apply/direct/driver.py`) drives an **already-open browser
over CDP**, fills a **fillable web form**, and refuses to submit on uncertainty. It has
**no authentication/login support**. So a portal whose apply flow requires a logged-in
session cannot be applied to deterministically — and automating a logged-in session on
the user's real account violates these portals' ToS and risks a **ban** (the user's
actual job hunt).

Per-portal recon (evidence-backed):

| Portal | Apply mechanism | Login to apply? | Bot posture | Deterministic no-login apply? |
|---|---|---|---|---|
| **Naukri** | Internal apply / "I'm interested" | **Yes** | Aggressive bot detection; automation = ToS violation, suspension risk | ❌ Blocked (login wall + ban risk) |
| **Instahyre** | Internal, curated, AI-matched | **Yes** | Curated/gated | ❌ Blocked (login) |
| **Cutshort** | Internal apply | **Yes** | Gated | ❌ Blocked (login) |
| **Hirist** | Internal apply | **Yes** | Gated | ❌ Blocked (login) |
| **Wellfound** | One-click "apply with your profile" (on-platform) | **Yes** | Stealth/anti-bot | ❌ Blocked (login; on-platform) |
| **startup.jobs** | Redirects to external company/ATS page | n/a on-site | **403 to automated fetch** (bot mitigation) — confirmed live | ⚠️ Discovery blocked for direct fetch; apply happens on the external ATS, not on startup.jobs |
| **Apna** | Mobile-first internal apply | **Yes** | App-gated | ❌ Blocked (login) |

**Conclusion:** every India-*native* portal hits the "completely blocked" condition you
named — login wall and/or bot mitigation — for deterministic, no-Claude, no-account
apply. Building a Naukri/Instahyre/Cutshort form adapter would not work without
automating the user's logged-in account (ban risk), which the current engine doesn't
support and which the project brief explicitly flags as a do-not.

---

## 3. Where deterministic no-Claude apply DOES work

The engine works on **no-login external application forms** — company career pages and
ATS that render a fillable form without auth: **Lever, Workday, SmartRecruiters,
Recruitee, BambooHR, Breezy, plain company forms** (and Greenhouse/Ashby, now excluded
by request). Many Indian employers host their careers on these.

So the achievable India-first, deterministic, $0-Claude path is:
**discover India-located roles → apply only to those that route to a no-login external
form → run in `--deterministic-only`.** Greenhouse/Ashby are now skipped.

India discovery sources already exist in `config/sites.yaml` (Cutshort, Hirist,
TimesJobs, MonsterIndia, Apna, Shiksha, Startup.jobs) — but they feed *discovery*, not
deterministic apply, because their apply is login-walled.

---

## 4. Recommended next steps (decision needed)

Two viable tracks — they need your input because they trade off automation vs account risk:

**Track A — Deterministic, no login, no Claude (works now, safe).**
Focus apply on India employers whose careers run on no-login ATS (Lever/Workday/etc.) or
plain company forms. Concretely: seed `career_targets`/`watchlist` with Indian companies'
career pages, discover India roles, apply with `--deterministic-only`. No account, no ban
risk, $0 Claude. Lower volume, but trustworthy.

**Track B — Login portals (Naukri/Wellfound/Instahyre), consent-gated.**
Requires: (a) a **persistent logged-in browser profile** using *your* account, (b) an
auth-aware apply path (the Driver would need a "use the signed-in session, don't submit
on uncertainty" mode), and (c) explicit acceptance of **ToS/ban risk** plus hard
rate-limiting. This is a separate build, one portal at a time, and should start with
whichever portal you actually have an account on and are willing to risk.

I did **not** fabricate a Naukri/Instahyre adapter that can't work without your login —
that would fail silently in production. Tell me which track (and for Track B, which
portal + that you accept the ban risk and will provide a logged-in session), and I'll
build it one portal at a time with the no-Claude guarantee intact.
