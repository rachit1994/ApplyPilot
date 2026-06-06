# India LinkedIn → Company Apply — Runbook

Goal: low ban-risk pipeline. Use LinkedIn to find **India** openings, click through
to capture the **employer's own apply URL** (never the linkedin.com URL), then
submit deterministically on the company form with **zero Claude**. Success =
application actually submitted + confirmation email received.

## One-time
```bash
# already done once: DB wiped clean
python scripts/clean_db.py --yes
```

## 1. Harvest India apply-URLs from LinkedIn
```bash
python scripts/linkedin_harvest.py --keywords "backend engineer" --max 25
```
- A **visible Chrome** opens (persistent profile, port 9222). **Log into LinkedIn** —
  the script waits, then continues automatically. Login persists for next time.
- It searches India (`geoId=102713980`), opens each job, clicks the real **Apply**
  button, and stores **only the redirected employer/ATS URL**.
- **Easy Apply** jobs are skipped (on-LinkedIn login apply, no external URL).
- For every company it touches, it also harvests that company's **other open India
  roles** and stores their apply URLs (`--no-expand` to disable, `--max-company N`).

## 2. Apply deterministically (no Claude; greenhouse/ashby excluded)
```bash
APPLYPILOT_SKIP_ATS_FAMILIES=greenhouse,ashby applypilot apply --deterministic-only
```
- Reuses the **same logged-in Chrome profile**, fills + submits on each employer form.
- Non-fillable / login-walled / unknown-ATS forms **park as `needs_adapter`** (never
  escalate to Claude).
- With `require_gmail_confirmation` on (default), an apply only counts as `applied`
  once the **confirmation email** is matched — that is the success metric.

## 2b. Login-required providers — pause & resume
Direct Apply now **attempts any provider form** (generic filler for plain company
forms + Indian ATS like Keka/Darwinbox/Zoho/Freshteam), not just Greenhouse/Lever/
Ashby. When a provider shows a **login wall**, the run does NOT fail — it:
- parks that job `awaiting_login` (reversible),
- shows **AWAITING LOGIN: <domain>** on the dashboard,
- and **pauses that worker** waiting for you.

You then **log into that provider** in the same visible Chrome and **Resume**:
```bash
python scripts/login_resume.py                       # see what's waiting
python scripts/login_resume.py --resume               # resume all
python scripts/login_resume.py --resume --domain naukri.com
```
or from the web dashboard: `GET /api/login/pending`, `POST /api/login/resume`.
Resuming clears the gate and re-queues the parked jobs — now behind your session.

Toggles: `APPLYPILOT_DIRECT_GENERIC=0` disables the generic attempt;
`APPLYPILOT_SKIP_ATS_FAMILIES=greenhouse,ashby` keeps those excluded.

## 3. See what's working
```bash
applypilot inbox scan-gmail        # classify recruiter/confirmation mail
applypilot inbox reply-report      # replies by source
```

## Known caveats (first-run tuning expected)
- **LinkedIn DOM selectors** (`_SEL` in `discovery/linkedin_harvest.py`) are
  centralized; LinkedIn A/B-tests its markup, so the first live run may need a
  selector tweak. Run with a small `--max 5` first and watch the logged
  `Captured:` / `Skip (reason):` lines.
- **Indian-ATS forms** (Keka, Darwinbox, Zoho Recruit, Freshteam, greytHR) don't yet
  have tuned adapters — they currently park as `needs_adapter` rather than submit.
  Next step: add a thin adapter per ATS from a real captured form (button/success
  markers), one at a time.
- If LinkedIn rate-limits/IP-blocks the harvest, lower `--max`, slow down, or pause —
  then move to the next keyword set.
