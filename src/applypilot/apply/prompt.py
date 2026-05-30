"""Prompt builder for the autonomous job application agent.

Constructs the full instruction prompt that tells Claude Code / the AI agent
how to fill out a job application form using Playwright MCP tools. All
personal data is loaded from the user's profile -- nothing is hardcoded.
"""

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from applypilot import config
from applypilot.apply import apply_settings
from applypilot.apply import prompt_scripts
from applypilot.apply.salary import get_min_annual_inr

logger = logging.getLogger(__name__)


def ensure_resume_pdf(resume_path: str | Path) -> Path:
    """Return the tailored resume PDF path, generating from .txt if needed."""
    if not resume_path:
        raise ValueError("No tailored resume path")

    base = Path(resume_path)
    pdf_path = base if base.suffix.lower() == ".pdf" else base.with_suffix(".pdf")
    pdf_path = pdf_path.resolve()
    if pdf_path.exists():
        return pdf_path

    txt_path = base if base.suffix.lower() == ".txt" else base.with_suffix(".txt")
    txt_path = txt_path.resolve()
    if not txt_path.exists():
        raise ValueError(f"Resume PDF not found: {pdf_path}")

    from applypilot.scoring.pdf import convert_to_pdf

    logger.info("Generating missing resume PDF from %s", txt_path.name)
    try:
        return Path(convert_to_pdf(txt_path)).resolve()
    except Exception as exc:
        raise ValueError(
            f"Resume PDF not found: {pdf_path} "
            f"(failed to generate from {txt_path.name}: {exc})"
        ) from exc


def _build_profile_summary(profile: dict) -> str:
    """Format the applicant profile section of the prompt.

    Reads all relevant fields from the profile dict and returns a
    human-readable multi-line summary for the agent.
    """
    p = profile
    personal = p["personal"]
    work_auth = p["work_authorization"]
    comp = p["compensation"]
    exp = p.get("experience", {})
    avail = p.get("availability", {})
    eeo = p.get("eeo_voluntary", {})

    lines = [
        f"Name: {personal['full_name']}",
        f"Email: {personal['email']}",
        f"Phone: {personal['phone']}",
    ]

    # Address -- handle optional fields gracefully
    addr_parts = [
        personal.get("address", ""),
        personal.get("city", ""),
        personal.get("province_state", ""),
        personal.get("country", ""),
        personal.get("postal_code", ""),
    ]
    lines.append(f"Address: {', '.join(p for p in addr_parts if p)}")

    if personal.get("linkedin_url"):
        lines.append(f"LinkedIn: {personal['linkedin_url']}")
    if personal.get("github_url"):
        lines.append(f"GitHub: {personal['github_url']}")
    if personal.get("portfolio_url"):
        lines.append(f"Portfolio: {personal['portfolio_url']}")
    if personal.get("website_url"):
        lines.append(f"Website: {personal['website_url']}")

    # Work authorization
    lines.append(f"Work Auth: {work_auth.get('legally_authorized_to_work', 'See profile')}")
    lines.append(f"Sponsorship Needed: {work_auth.get('require_sponsorship', 'See profile')}")
    if work_auth.get("work_permit_type"):
        lines.append(f"Work Permit: {work_auth['work_permit_type']}")

    # Compensation
    currency = comp.get("salary_currency", "USD")
    lines.append(f"Salary Expectation: {comp['salary_expectation']} {currency}")

    # Experience
    if exp.get("years_of_experience_total"):
        lines.append(f"Years Experience: {exp['years_of_experience_total']}")
    if exp.get("education_level"):
        lines.append(f"Education: {exp['education_level']}")
    from applypilot.config import get_target_roles

    roles = get_target_roles(profile)
    if roles:
        lines.append(f"Target roles: {', '.join(roles)}")

    # Availability
    lines.append(f"Available: {avail.get('earliest_start_date', 'Immediately')}")

    # Standard responses
    lines.extend([
        "Age 18+: Yes",
        "Background Check: Yes",
        "Felony: No",
        "Previously Worked Here: No",
        "How Heard: Online Job Board",
    ])

    # EEO
    lines.append(f"Gender: {eeo.get('gender', 'Decline to self-identify')}")
    lines.append(f"Race: {eeo.get('race_ethnicity', 'Decline to self-identify')}")
    lines.append(f"Veteran: {eeo.get('veteran_status', 'I am not a protected veteran')}")
    lines.append(f"Disability: {eeo.get('disability_status', 'I do not wish to answer')}")

    return "\n".join(lines)


def _build_location_check(profile: dict, search_config: dict) -> str:
    """Build the location eligibility check section of the prompt.

    Uses the accept_patterns from search config to determine which cities
    are acceptable for hybrid/onsite roles.
    """
    personal = profile["personal"]
    location_cfg = search_config.get("location", {})
    accept_patterns = location_cfg.get("accept_patterns", [])
    primary_city = personal.get("city", location_cfg.get("primary", "your city"))

    # Build the list of acceptable cities for hybrid/onsite
    if accept_patterns:
        city_list = ", ".join(accept_patterns)
    else:
        city_list = primary_city

    return f"""== LOCATION CHECK (do this FIRST before any form) ==
Read the job page. Determine the work arrangement. Then decide:
- "Remote" or "work from anywhere" -> ELIGIBLE. Apply.
- "Hybrid" or "onsite" in {city_list} -> ELIGIBLE. Apply.
- "Hybrid" or "onsite" in another city BUT the posting also says "remote OK" or "remote option available" -> ELIGIBLE. Apply.
- "Onsite only" or "hybrid only" in any city outside the list above with NO remote option -> NOT ELIGIBLE. Stop immediately. Output RESULT:FAILED:not_eligible_location
- City is overseas (India, Philippines, Europe, etc.) with no remote option -> NOT ELIGIBLE. Output RESULT:FAILED:not_eligible_location
- Cannot determine location -> Continue applying. If a screening question reveals it's non-local onsite, answer honestly and let the system reject if needed.
Do NOT fill out forms for jobs that are clearly onsite in a non-acceptable location. Check EARLY, save time."""


def _build_workatastartup_location_check() -> str:
    return """== LOCATION CHECK (Work at a Startup — remote-first listing) ==
This listing is filtered for remote roles with disclosed salary. Apply unless the role is clearly internship-only onsite with no remote path.

ELIGIBLE: Remote, distributed, hybrid with remote option, US/EU/India/global remote, "work from anywhere".
Do NOT output RESULT:FAILED:not_eligible_location for US or international remote jobs on this site.
If location is unclear, continue and apply."""


def _build_salary_eligibility_check(profile: dict) -> str:
    """Build the salary eligibility check section of the prompt."""
    from applypilot.apply.salary import get_apply_floor_inr, get_apply_floor_usd

    min_inr = get_apply_floor_inr()
    min_usd = get_apply_floor_usd()
    india_lakhs = min_inr // 100_000
    return f"""== SALARY CHECK (do this right after location) ==
Regional minimums for full-time salaried roles:
- India-based (INR / LPA / ₹, or location in India): upper bound must be at least {india_lakhs} lakhs per annum ({min_inr:,} INR/year).
- All other countries (USD / $): upper bound must be at least ${min_usd:,} USD/year.
- No salary or compensation range shown anywhere on the posting -> ELIGIBLE. Continue and apply.
- Listed pay below the applicable regional minimum -> NOT ELIGIBLE. Stop immediately. Output RESULT:FAILED:not_eligible_salary
- If only a monthly figure is shown, convert to annual before comparing.
- Hourly/contract pay -> NOT ELIGIBLE (already covered under hard rules).
Do NOT submit for roles clearly below the minimum when pay is listed."""


def _build_salary_section(profile: dict) -> str:
    """Build the salary negotiation instructions.

    Adapts floor, range, and currency from the profile's compensation section.
    """
    comp = profile["compensation"]
    currency = comp.get("salary_currency", "USD")
    floor = comp["salary_expectation"]
    range_min = comp.get("salary_range_min", floor)
    range_max = comp.get("salary_range_max", str(int(floor) + 20000) if floor.isdigit() else floor)
    conversion_note = comp.get("currency_conversion_note", "")
    floor_label = f"{floor} {currency}"
    if currency.upper() == "INR" and floor.isdigit():
        floor_label = f"{int(floor) // 100_000} lakhs per annum ({floor} {currency})"

    # Compute example hourly rates at 3 salary levels
    try:
        floor_int = int(floor)
        examples = [
            (f"${floor_int // 1000}K", floor_int // 2080),
            (f"${(floor_int + 25000) // 1000}K", (floor_int + 25000) // 2080),
            (f"${(floor_int + 55000) // 1000}K", (floor_int + 55000) // 2080),
        ]
        hourly_line = ", ".join(f"{sal} = ${hr}/hr" for sal, hr in examples)
    except (ValueError, TypeError):
        hourly_line = "Divide annual salary by 2080"

    # Currency conversion guidance
    if conversion_note:
        convert_line = f"Posting is in a different currency? -> {conversion_note}"
    else:
        convert_line = "Posting is in a different currency? -> Target midpoint of their range. Convert if needed."

    return f"""== SALARY (think, don't just copy) ==
{floor_label} is the FLOOR. Never go below it. But don't always use it either.

Decision tree:
1. Job posting shows a range (e.g. "$120K-$160K")? -> Answer with the MIDPOINT ($140K).
2. Title says Senior, Staff, Lead, Principal, Architect, or level II/III/IV? -> Minimum $110K {currency}. Use midpoint of posted range if higher.
3. {convert_line}
4. No salary info anywhere? -> Use {floor_label}.
5. Asked for a range? -> Give posted midpoint minus 10% to midpoint plus 10%. No posted range? -> "{range_min}-{range_max} {currency}".
6. Hourly rate? -> Divide your annual answer by 2080. ({hourly_line})"""


def _build_screening_section(profile: dict) -> str:
    """Build the screening questions guidance section."""
    personal = profile["personal"]
    exp = profile.get("experience", {})
    city = personal.get("city", "their city")
    years = exp.get("years_of_experience_total", "multiple")
    from applypilot.config import get_target_roles

    roles = get_target_roles(profile)
    target_role = exp.get("target_role", personal.get("current_job_title", "software engineer"))
    roles_line = ", ".join(roles) if roles else target_role
    work_auth = profile["work_authorization"]

    return f"""== SCREENING QUESTIONS (be strategic) ==
Hard facts -> answer truthfully from the profile. No guessing. This includes:
  - Location/relocation: based in {city}; open to remote and distributed roles globally
  - Work authorization: {work_auth.get('legally_authorized_to_work', 'see profile')}
  - Citizenship, clearance, licenses, certifications: answer from profile only
  - Criminal/background: answer from profile only

Skills and tools -> be confident. This candidate targets roles such as: {roles_line}. They have {years} years experience. If the question asks "Do you have experience with [tool]?" and it's in the same domain (DevOps, backend, ML, cloud, automation, AI), answer YES. Software engineers learn tools fast. Don't sell short.

Open-ended questions ("Why do you want this role?", "Tell us about yourself", "What interests you?") -> Write 2-3 sentences. Be specific to THIS job. Reference something from the job description. Connect it to a real achievement from the resume. No generic fluff. No "I am passionate about..." -- sound like a real person.

EEO/demographics -> "Decline to self-identify" or "Prefer not to say" for everything."""


def _build_hard_rules(profile: dict) -> str:
    """Build the hard rules section with work auth and name from profile."""
    personal = profile["personal"]
    work_auth = profile["work_authorization"]

    full_name = personal["full_name"]
    preferred_name = personal.get("preferred_name", full_name.split()[0])
    preferred_last = full_name.split()[-1] if " " in full_name else ""
    display_name = f"{preferred_name} {preferred_last}".strip() if preferred_last else preferred_name

    # Build work auth rule dynamically
    auth_info = work_auth.get("legally_authorized_to_work", "")
    sponsorship = work_auth.get("require_sponsorship", "")
    permit_type = work_auth.get("work_permit_type", "")

    work_auth_rule = "Work auth: Answer truthfully from profile."
    if permit_type:
        work_auth_rule = f"Work auth: {permit_type}. Sponsorship needed: {sponsorship}."

    name_rule = f'Name: Legal name = {full_name}.'
    if preferred_name and preferred_name != full_name.split()[0]:
        name_rule += f' Preferred name = {preferred_name}. Use "{display_name}" unless a field specifically says "legal name".'

    return f"""== HARD RULES (never break these) ==
1. Never lie about: citizenship, work authorization, criminal history, education credentials, security clearance, licenses.
2. {work_auth_rule}
3. {name_rule}"""


def _build_captcha_section() -> str:
    """Build the CAPTCHA detection and solving instructions.

    Reads the CapSolver API key from environment. Browser helper scripts live in
    prompt_scripts.py so slim mode can omit this entire section.
    """
    config.load_env()
    capsolver_key = os.environ.get("CAPSOLVER_API_KEY", "")
    create_task_js = prompt_scripts.format_captcha_create_task(capsolver_key)
    poll_js = prompt_scripts.format_captcha_poll(capsolver_key)

    return f"""== CAPTCHA ==
You solve CAPTCHAs via the CapSolver REST API. No browser extension. You control the entire flow.
API key: {capsolver_key or 'NOT CONFIGURED — skip to MANUAL FALLBACK for all CAPTCHAs'}
API base: https://api.capsolver.com

CRITICAL RULE: When ANY CAPTCHA appears (hCaptcha, reCAPTCHA, Turnstile -- regardless of what it looks like visually), you MUST:
1. Run CAPTCHA DETECT to get the type and sitekey
2. Run CAPTCHA SOLVE (createTask -> poll -> inject) with the CapSolver API
3. ONLY go to MANUAL FALLBACK if CapSolver returns errorId > 0
Do NOT skip the API call based on what the CAPTCHA looks like. CapSolver solves CAPTCHAs server-side -- it does NOT need to see or interact with images, puzzles, or games. Even "drag the pipe" or "click all traffic lights" hCaptchas are solved via API token, not visually. ALWAYS try the API first.

--- CAPTCHA DETECT ---
Run this browser_evaluate after every navigation, Apply/Submit/Login click, or when a page feels stuck.
IMPORTANT: Detection order matters. hCaptcha elements also have data-sitekey, so check hCaptcha BEFORE reCAPTCHA.

browser_evaluate function: {prompt_scripts.CAPTCHA_DETECT_JS}

Result actions:
- null -> no CAPTCHA. Continue normally.
- "turnstile_script_only" -> browser_wait_for time: 3, re-run detect.
- Any other type -> proceed to CAPTCHA SOLVE below.

--- CAPTCHA SOLVE ---
Three steps: createTask -> poll -> inject. Do each as a separate browser_evaluate call.

STEP 1 -- CREATE TASK (copy this exactly, fill in the 3 placeholders):
browser_evaluate function: {create_task_js}

TASK_TYPE values (use EXACTLY these strings):
  hcaptcha     -> HCaptchaTaskProxyLess
  recaptchav2  -> ReCaptchaV2TaskProxyLess
  recaptchav3  -> ReCaptchaV3TaskProxyLess
  turnstile    -> AntiTurnstileTaskProxyLess
  funcaptcha   -> FunCaptchaTaskProxyLess

PAGE_URL = the url from detect result. SITE_KEY = the sitekey from detect result.
For recaptchav3: add "pageAction": "submit" to the task object (or the actual action found in page scripts).
For turnstile: add "metadata": {{"action": "...", "cdata": "..."}} if those were in detect result.

Response: {{"errorId": 0, "taskId": "abc123"}} on success.
If errorId > 0 -> CAPTCHA SOLVE failed. Go to MANUAL FALLBACK.

STEP 2 -- POLL (replace TASK_ID with the taskId from step 1):
Loop: browser_wait_for time: 3, then run:
browser_evaluate function: {poll_js}

- status "processing" -> wait 3s, poll again. Max 10 polls (30s).
- status "ready" -> extract token:
    reCAPTCHA: solution.gRecaptchaResponse
    hCaptcha:  solution.gRecaptchaResponse
    Turnstile: solution.token
- errorId > 0 or 30s timeout -> MANUAL FALLBACK.

STEP 3 -- INJECT TOKEN (replace THE_TOKEN with actual token string):

For reCAPTCHA v2/v3:
browser_evaluate function: {prompt_scripts.CAPTCHA_INJECT_RECAPTCHA_JS}

For hCaptcha:
browser_evaluate function: {prompt_scripts.CAPTCHA_INJECT_HCAPTCHA_JS}

For Turnstile:
browser_evaluate function: {prompt_scripts.CAPTCHA_INJECT_TURNSTILE_JS}

For FunCaptcha:
browser_evaluate function: {prompt_scripts.CAPTCHA_INJECT_FUNCAPTCHA_JS}

After injecting: browser_wait_for time: 2, then snapshot.
- Widget gone or green check -> success. Click Submit if needed.
- No change -> click Submit/Verify/Continue button (some sites need it).
- Still stuck -> token may have expired (~2 min lifetime). Re-run from STEP 1.

--- MANUAL FALLBACK ---
You should ONLY be here if CapSolver createTask returned errorId > 0. If you haven't tried CapSolver yet, GO BACK and try it first.
If CapSolver genuinely failed (errorId > 0):
1. Audio challenge: Look for "audio" or "accessibility" button -> click it for an easier challenge.
2. Text/logic puzzles: Solve them yourself. Think step by step. Common tricks: "All but 9 die" = 9 left. "3 sisters and 4 brothers, how many siblings?" = 7.
3. Simple text captchas ("What is 3+7?", "Type the word") -> solve them.
4. All else fails -> Output RESULT:CAPTCHA."""


def _build_email_verification_section(email: str) -> str:
    """Instructions for ATS email verification codes after submit."""
    return f"""== EMAIL VERIFICATION (mandatory when any page asks for an email/security code) ==
Many ATS systems send a 4-8 character verification code after Submit/Apply.
You MUST handle this with Gmail MCP tools. NEVER open gmail.com in the browser.
NEVER ask the human to paste the code unless Gmail MCP fails after all retries.

When the page says a code was sent to {email}, or asks for a security code:
1. Keep the application tab open. Wait 20-30 seconds for mail delivery.
2. Use mcp__gmail__search_emails with maxResults 10 and this query:
   newer_than:10m (from:greenhouse OR from:lever OR from:ashby OR from:workday OR from:no-reply OR from:noreply OR from:donotreply OR subject:verification OR subject:code)
3. Pick the newest plausible message for this application. Prefer messages mentioning the company, ATS, "verification", "security code", or "confirm your email".
4. Use mcp__gmail__read_email on that message.
5. Extract the code: usually a standalone 4-8 character alphanumeric string, often uppercase, for example ABC12345 or 123456.
6. Switch back to the application tab with browser_tabs, type the code, and click Verify/Continue/Submit.
7. Snapshot the post-verify state. If you see "application submitted", "thanks for applying", "confirmation", or a confirmation URL, emit status:"applied".
8. Include "verification_code_used":"<code>" in RESULT_JSON when a code was used.

Retry policy: if no email is found, wait 30 seconds and repeat search/read up to 4 total attempts.
If still no code arrives, emit RESULT_JSON status:"failed" reason:"email_code_not_received".
"""


def _build_pacing_section(pace_seconds: float, confirm_submit: bool) -> str:
    """Instructions to slow the agent for a visible browser a human can follow."""
    if pace_seconds <= 0 and not confirm_submit:
        return ""

    wait = max(int(pace_seconds), 1) if pace_seconds > 0 else 0
    confirm_wait = max(int(pace_seconds * 5), 45) if confirm_submit else 0
    lines = [
        "== HUMAN PACE (visible browser — go slow) ==",
        "A person is watching this Chrome window. They need time to see each step.",
    ]
    if wait:
        lines.extend([
            f"- After EVERY browser action (navigate, click, fill, upload, select tab), "
            f"run browser_wait_for with time: {wait} before the next action.",
            "- Fill at most 5 fields per browser_fill_form call, then wait, then continue.",
            "- On multi-page forms: complete one page, wait, snapshot, then click Next.",
            "- Do NOT rush. Short thinking is fine, but do not skip waits.",
        ])
    if confirm_submit:
        lines.extend([
            f"- BEFORE clicking Submit/Apply (or finishing a dry run): browser_snapshot, "
            f"browser_take_screenshot, then browser_wait_for time: {confirm_wait} so the "
            "human can review every field in the browser.",
            "- After the wait, re-check the snapshot. Fix anything wrong, then proceed.",
        ])
    return "\n".join(lines)


def _build_page_grounding_section(human_pace: bool, *, include_captcha: bool = True) -> str:
    lines = [
        "== PAGE GROUNDING (required) ==",
        "- Use browser_snapshot for element refs. Take a NEW snapshot whenever the page may have changed.",
        "- MUST re-snapshot after: browser_navigate; any click on Apply/Next/Continue/Submit/Login/Sign in; "
        "browser_tabs select; resume or cover letter upload; each browser_fill_form batch.",
        "- Never click or fill using refs from an older snapshot.",
        "- Fill at most 5 fields per browser_fill_form call. After each batch: run VERIFY PAGE STATE. "
        "If fields are empty or wrong, fix before continuing.",
        "- Multi-page forms (Workday, Taleo, iCIMS, Greenhouse): snapshot → fill in batches (≤5) → "
        "VERIFY → click Next → browser_wait_for time: 2 → snapshot the NEW page.",
        "- If an action does nothing (same URL, same errors): snapshot again, run VERIFY, try a different ref.",
        "- browser_take_screenshot is optional; use snapshot + VERIFY for decisions, not screenshots alone.",
    ]
    if include_captcha:
        lines.append("- After navigation, Apply/Submit/Login, or when stuck: run CAPTCHA DETECT.")
    if human_pace:
        lines.append("- Human pace mode: also follow HUMAN PACE waits between actions.")
    return "\n".join(lines)


def _extract_experience_ranges(resume_text: str) -> list[dict[str, str]]:
    """Extract simple title/company/date ranges for ATS date repair guidance."""
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    rows: list[dict[str, str]] = []
    year_pattern = re.compile(r"\b(20\d{2}|19\d{2})\b")

    for index, line in enumerate(lines):
        years = year_pattern.findall(line)
        if not years:
            continue
        if "|" not in line:
            continue

        title = line.split("|", 1)[0].strip()
        company_line = lines[index + 1] if index + 1 < len(lines) else ""
        company = re.split(r"\s+[·|]\s+", company_line, maxsplit=1)[0].strip()
        is_current = "present" in line.lower() or "current" in line.lower()

        rows.append(
            {
                "title": title,
                "company": company,
                "start_month": "01",
                "start_year": years[0],
                "end_month": "" if is_current else "12",
                "end_year": "" if is_current else years[-1],
                "current": "yes" if is_current else "no",
            }
        )

    return rows


def _build_ats_form_repair_section(resume_text: str) -> str:
    rows = _extract_experience_ranges(resume_text)
    examples = []
    for row in rows[:6]:
        to_value = "Present" if row["current"] == "yes" else f"{row['end_month']}/{row['end_year']}"
        examples.append(
            f"- {row['company']} / {row['title']}: "
            f"from={row['start_month']}/{row['start_year']} to={to_value}"
        )
    example_text = "\n".join(examples) if examples else "- Use the resume dates exactly."

    return f"""== ATS FORM REPAIR ==
If an ATS form shows Invalid Date, missing/sparse experience rows, or parsed resume fields that conflict with the page bodyText, repair the form before moving on.
- Never leave a Month field as "MM"; use 01 for start months and 12 for past-job end months when the resume has only a year.
- For current roles, set current/present if available and leave end month/year blank if the ATS allows it.
- On any multi-step ATS form, run VERIFY PAGE STATE after each page and fix invalidFields before clicking Next.
- Compare generated rows with bodyText and the resume. Do not trust ATS parsing blindly.

Known resume date ranges:
{example_text}"""


def _build_form_verify_section() -> str:
    return f"""== VERIFY PAGE STATE (run often) ==
After each fill batch, upload, or before Next/Submit, run this browser_evaluate to read what is actually on the page:

browser_evaluate function: {prompt_scripts.FORM_VERIFY_JS}

How to use the result:
- If emptyRequired > 0, fill those fields before Next/Submit.
- If visibleErrors is non-empty, fix those fields first.
- If you expected a new page after Next but url/title are unchanged, snapshot and find the real Next/Apply control.
- Do NOT click Submit until emptyRequired is 0 and visibleErrors is empty (unless dry run)."""


def _build_form_verify_section_slim() -> str:
    return """== VERIFY PAGE STATE (run often) ==
After each fill batch, upload, or before Next/Submit:
1. browser_snapshot and read visible fields, errors, and buttons from the snapshot.
2. If required fields look empty or validation errors are visible, fix them before Next/Submit.
3. If you expected a new page after Next but the URL/title did not change, snapshot again and find the real control.
4. Do NOT click Submit until required fields are filled and validation errors are cleared (unless dry run)."""


def _build_ats_form_repair_section_slim(resume_text: str) -> str:
    rows = _extract_experience_ranges(resume_text)
    examples = []
    for row in rows[:6]:
        to_value = "Present" if row["current"] == "yes" else f"{row['end_month']}/{row['end_year']}"
        examples.append(
            f"- {row['company']} / {row['title']}: "
            f"from={row['start_month']}/{row['start_year']} to={to_value}"
        )
    example_text = "\n".join(examples) if examples else "- Use the resume dates exactly."
    return f"""== ATS FORM REPAIR ==
If dates or experience rows look wrong, fix them before Next/Submit.
- Never leave Month as "MM"; use 01 for starts and 12 for past end months when only a year is known.
- For current roles, mark present/current and leave end date blank when allowed.
Known resume date ranges:
{example_text}"""


def _build_captcha_section_slim() -> str:
    return """== CAPTCHA (only when visible) ==
If browser_snapshot shows reCAPTCHA, hCaptcha, or Turnstile blocking progress:
1. Try CapSolver via browser_evaluate (createTask/getTaskResult) if CAPSOLVER_API_KEY is set.
2. Inject the token, snapshot again, and continue.
3. If automation fails after one attempt, emit RESULT_JSON status "captcha"."""


def _build_email_verification_section_slim(email: str) -> str:
    return f"""== EMAIL VERIFICATION ==
If the page asks for a code sent to {email}:
1. Wait 20-30s, then use mcp__gmail__search_emails (newer_than:10m) and mcp__gmail__read_email.
2. Type the code in the application tab and continue.
3. If no code after several searches, emit RESULT_JSON status failed reason email_code_not_received."""


def _is_workatastartup_job(job: dict) -> bool:
    url = (job.get("url") or "") + (job.get("application_url") or "")
    strategy = (job.get("strategy") or "").lower()
    return "workatastartup.com" in url or strategy == "workatastartup"


def _build_workatastartup_apply_section(cover_letter_text: str) -> str:
    message = cover_letter_text.strip() or "(use COVER LETTER TEXT below)"
    return f"""== WORK AT A STARTUP (message application — NOT an ATS form) ==
This is Y Combinator Work at a Startup. Do NOT fill long employer application forms.
Your job is to log in, open the application page, paste a personalized message, and submit.

Flow:
1. browser_navigate to the application URL (signup_job_id link), not only the job listing.
2. If redirected to account.ycombinator.com, log in with the profile email and password.
   If password is empty or login fails, STOP and output RESULT:FAILED:login_issue — user must log in manually once.
3. On the application page, find the main text area for your message to the founder/team.
4. browser_fill or browser_type the APPLICATION MESSAGE below (not a cover letter format — plain paragraphs).
5. Attach/upload resume PDF only if the page has a resume upload field (optional on WaaS).
6. Do NOT invent extra form fields. If the page is only message + optional resume, submit after the message is pasted.
7. Click the primary Submit / Apply / Send button once message and resume (if required) are set.

APPLICATION MESSAGE (paste exactly, you may fix obvious typos only):
{message}
"""


def build_prompt(job: dict, tailored_resume: str,
                 cover_letter: str | None = None,
                 dry_run: bool = False,
                 pace_seconds: float = 0.0,
                 confirm_submit: bool = False,
                 upload_dir: Path | None = None) -> str:
    """Build the full instruction prompt for the apply agent.

    Loads the user profile and search config internally. All personal data
    comes from the profile -- nothing is hardcoded.

    Args:
        job: Job dict from the database (must have url, title, site,
             application_url, fit_score, tailored_resume_path).
        tailored_resume: Plain-text content of the tailored resume.
        cover_letter: Optional plain-text cover letter content.
        dry_run: If True, tell the agent not to click Submit.
        pace_seconds: Seconds to wait between browser actions (0 = fast).
        confirm_submit: Pause with snapshot + long wait before Submit.

    Returns:
        Complete prompt string for the AI agent.
    """
    profile = config.load_profile()
    search_config = config.load_search_config()
    personal = profile["personal"]

    # --- Resolve resume PDF path ---
    resume_path = job.get("tailored_resume_path")
    if not resume_path:
        raise ValueError(f"No tailored resume for job: {job.get('title', 'unknown')}")

    src_pdf = ensure_resume_pdf(resume_path)

    # Copy to a clean filename for upload (recruiters see the filename)
    full_name = personal["full_name"]
    name_slug = full_name.replace(" ", "_")
    dest_dir = upload_dir or (config.APPLY_WORKER_DIR / "current")
    dest_dir.mkdir(parents=True, exist_ok=True)
    upload_pdf = dest_dir / f"{name_slug}_Resume.pdf"
    shutil.copy(str(src_pdf), str(upload_pdf))
    pdf_path = str(upload_pdf)

    # --- Cover letter handling ---
    cover_letter_text = cover_letter or ""
    cl_upload_path = ""
    cl_path = job.get("cover_letter_path")
    if cl_path and Path(cl_path).exists():
        cl_src = Path(cl_path)
        # Read text from .txt sibling (PDF is binary)
        cl_txt = cl_src.with_suffix(".txt")
        if cl_txt.exists():
            cover_letter_text = cl_txt.read_text(encoding="utf-8")
        elif cl_src.suffix == ".txt":
            cover_letter_text = cl_src.read_text(encoding="utf-8")
        # Upload must be PDF
        cl_pdf_src = cl_src.with_suffix(".pdf")
        if cl_pdf_src.exists():
            cl_upload = dest_dir / f"{name_slug}_Cover_Letter.pdf"
            shutil.copy(str(cl_pdf_src), str(cl_upload))
            cl_upload_path = str(cl_upload)

    # --- Build all prompt sections ---
    profile_summary = _build_profile_summary(profile)
    location_check = (
        _build_workatastartup_location_check()
        if _is_workatastartup_job(job)
        else _build_location_check(profile, search_config)
    )
    salary_eligibility_check = _build_salary_eligibility_check(profile)
    salary_section = _build_salary_section(profile)
    screening_section = _build_screening_section(profile)
    hard_rules = _build_hard_rules(profile)
    slim = apply_settings.prompt_slim_enabled()
    needs_captcha = apply_settings.job_likely_needs_captcha(job)
    needs_gmail = apply_settings.job_likely_needs_gmail(job)

    if slim and not needs_captcha:
        captcha_section = ""
    elif slim and needs_captcha:
        captcha_section = _build_captcha_section_slim()
    else:
        captcha_section = _build_captcha_section()

    if slim and not needs_gmail:
        email_verification_section = (
            f"== EMAIL VERIFICATION ==\n"
            f"If a verification code is required for {personal['email']}, enable Gmail MCP "
            f"(APPLYPILOT_APPLY_GMAIL_MCP=1) or emit pause_for_human.\n"
        )
    elif slim:
        email_verification_section = _build_email_verification_section_slim(personal["email"])
    else:
        email_verification_section = _build_email_verification_section(personal["email"])

    human_pace = pace_seconds > 0 or confirm_submit
    pacing_section = _build_pacing_section(pace_seconds, confirm_submit)
    page_grounding_section = _build_page_grounding_section(
        human_pace, include_captcha=bool(captcha_section)
    )
    if slim:
        ats_form_repair_section = _build_ats_form_repair_section_slim(tailored_resume)
        form_verify_section = _build_form_verify_section_slim()
    else:
        ats_form_repair_section = _build_ats_form_repair_section(tailored_resume)
        form_verify_section = _build_form_verify_section()
    waas = _is_workatastartup_job(job)
    workatastartup_section = (
        _build_workatastartup_apply_section(cover_letter_text)
        if waas
        else ""
    )

    # Cover letter fallback text
    city = personal.get("city", "the area")
    if not cover_letter_text:
        cl_display = (
            f"None available. Skip if optional. If required, write 2 factual "
            f"sentences: (1) relevant experience from the resume that matches "
            f"this role, (2) available immediately and based in {city}."
        )
    else:
        cl_display = cover_letter_text

    # Phone digits only (for fields with country prefix)
    phone_digits = "".join(c for c in personal.get("phone", "") if c.isdigit())

    # SSO domains the agent cannot sign into (loaded from config/sites.yaml)
    from applypilot.config import load_blocked_sso
    blocked_sso = load_blocked_sso()

    # Preferred display name
    preferred_name = personal.get("preferred_name", full_name.split()[0])
    last_name = full_name.split()[-1] if " " in full_name else ""
    display_name = f"{preferred_name} {last_name}".strip()

    # Dry-run: override submit instruction
    if dry_run:
        submit_instruction = (
            "IMPORTANT: Do NOT click the final Submit/Apply button. Review the form, verify all fields, "
            'then emit RESULT_JSON with status "dry_run" (include would_click_ref and would_click_text). '
            'Do NOT use status "applied" or legacy RESULT:APPLIED.'
        )
    else:
        submit_instruction = (
            "BEFORE clicking Submit/Apply: browser_snapshot, run VERIFY PAGE STATE, and review EVERY field. "
            "Verify all data matches the APPLICANT PROFILE and TAILORED RESUME -- name, email, phone, location, "
            "work auth, resume uploaded, cover letter if applicable. If emptyRequired > 0 or visibleErrors is "
            "non-empty, fix FIRST. Only click Submit after VERIFY passes."
        )

    job_url = str(job.get("application_url") or job["url"])
    linkedin_company_site_rule = ""
    if "linkedin.com/jobs" in job_url.lower():
        linkedin_company_site_rule = """
== LINKEDIN SPECIAL RULE ==
If this is a LinkedIn job page:
- DO NOT attempt LinkedIn Easy Apply.
- FIRST: look for a button/link like "Apply on company website" / "Apply to company website".
  - Click it.
  - If it opens a new tab/window, switch to it.
  - Capture the final external URL you land on (ATS/company site).
  - Continue the application on that external site.
- If there is NO "Apply on company website" option (only Easy Apply / no apply button):
  emit RESULT_JSON:{"status":"failed","reason":"linkedin_no_company_website_apply"} and stop.

If you used "Apply on company website", include "company_apply_url":"<external_url>" in your RESULT_JSON.
"""

    prompt = f"""You are an autonomous job application agent. Your ONE mission: get this candidate an interview. You have all the information and tools. Think strategically. Act decisively. Submit the application.

== JOB ==
URL: {job_url}
Title: {job['title']}
Company: {job.get('site', 'Unknown')}
Fit Score: {job.get('fit_score', 'N/A')}/10

== FILES ==
Resume PDF (upload this): {pdf_path}
Cover Letter PDF (upload if asked): {cl_upload_path or "N/A"}

== RESUME TEXT (use when filling text fields) ==
{tailored_resume}

== COVER LETTER TEXT (paste if text field, upload PDF if file field) ==
{cl_display}

== APPLICANT PROFILE ==
{profile_summary}

== YOUR MISSION ==
Submit a complete, accurate application. Use the profile and resume as source data -- adapt to fit each form's format.

If something unexpected happens and these instructions don't cover it, figure it out yourself. You are autonomous. Navigate pages, read content, try buttons, explore the site. The goal is always the same: submit the application. Do whatever it takes to reach that goal.

{hard_rules}

{linkedin_company_site_rule}

== NEVER DO THESE (immediate RESULT:FAILED if encountered) ==
- NEVER grant camera, microphone, screen sharing, or location permissions. If a site requests them -> RESULT:FAILED:unsafe_permissions
- NEVER do video/audio verification, selfie capture, ID photo upload, or biometric anything -> RESULT:FAILED:unsafe_verification
- NEVER set up a freelancing profile (Mercor, Toptal, Upwork, Fiverr, Turing, etc.). These are contractor marketplaces, not job applications -> RESULT:FAILED:not_a_job_application
- NEVER agree to hourly/contract rates, availability calendars, or "set your rate" flows. You are applying for FULL-TIME salaried positions only.
- NEVER install browser extensions, download executables, or run assessment software.
- NEVER enter payment info, bank details, or SSN/SIN.
- NEVER click "Allow" on any browser permission popup. Always deny/block.
- If the site is NOT a job application form (it's a profile builder, skills marketplace, talent network signup, coding assessment platform) -> RESULT:FAILED:not_a_job_application

{location_check}

{salary_eligibility_check}

{salary_section}

{screening_section}

{workatastartup_section}

== STEP-BY-STEP ==
1. browser_navigate to the job URL.
2. browser_snapshot to read the page. Run VERIFY PAGE STATE to see fields and buttons.{" Run CAPTCHA DETECT and solve before continuing if a CAPTCHA is visible." if captcha_section else ""}
3. LOCATION CHECK. Read the page for location info. If not eligible, output RESULT and stop.
4. SALARY CHECK. Read the page for compensation. If pay is listed and below the minimum, output RESULT:FAILED:not_eligible_salary and stop. If pay is not listed, continue.
5. Find and click the Apply button. If email-only (page says "email resume to X"):
   - send_email with subject "Application for {job['title']} -- {display_name}", body = 2-3 sentence pitch + contact info, attach resume PDF: ["{pdf_path}"]
   - Output RESULT:APPLIED. Done.
   After clicking Apply: browser_snapshot.{" Run CAPTCHA DETECT if a widget appears; solve before continuing." if captcha_section else ""}
5. Login wall?
   5a. FIRST: check the URL. If you landed on {', '.join(blocked_sso)}, treat it as SSO/OAuth.
       - Exception: Google SSO (accounts.google.com) is ALLOWED **only if you are already logged in**.
         If you see a "Continue with Google" / "Sign in with Google" button anywhere on the page, click it.
         Then decide:
           - If you see an account picker (e.g. "Choose an account", list of existing accounts) -> pick the matching {personal['email']} if present, otherwise pick the first account, then click Continue/Next.
           - If you are already logged in and see "Continue" / "Next" / "Continue as <name>" -> click through.
           - If you see ANY credential gate (email/password entry, "Use another account", passkey, 2FA, phone prompt, recovery, captchas that block login) -> STOP and output RESULT_JSON:{{"status":"pause_for_human","reason":"sso_login_needed"}}
       - Any other SSO (Microsoft/Okta/Auth0/etc.) -> RESULT_JSON:{{"status":"failed","reason":"sso_required"}}
   5b. Check for popups. Run browser_tabs action "list". If a new tab/window appeared (login popup), switch to it.
       Apply the same rules as 5a for that tab.
   5c. Regular login form (employer's own site)? Try sign in: {personal['email']} / {personal.get('password', '')}
   5d. After clicking Login/Sign-in:{" run CAPTCHA DETECT if login appears blocked." if captcha_section else " snapshot and retry login if blocked."}
   5e. Sign in failed? Try sign up with same email and password.
   5f. Need email verification? Use the EMAIL VERIFICATION section below.
   5g. After login, run browser_tabs action "list" again. Switch back to the application tab if needed.
   5h. All failed? Output RESULT:FAILED:login_issue. Do not loop.
6. Upload resume. ALWAYS upload fresh -- delete any existing resume first, then browser_file_upload with the PDF path above. browser_wait_for time: 3, browser_snapshot, run VERIFY PAGE STATE (confirm upload registered). Non-negotiable.
7. Upload cover letter if there's a field for it. Text field -> paste the cover letter text. File upload -> use the cover letter PDF path. VERIFY after upload.
8. Fill the form in batches of at most 5 fields per browser_fill_form. After EACH batch: run VERIFY PAGE STATE.
   Check ALL pre-filled fields. ATS systems parse your resume and auto-fill -- it's often WRONG.
   - "Current Job Title" or "Most Recent Title" -> use the title from the TAILORED RESUME summary, NOT whatever the parser guessed.
   - Compare every other field to the APPLICANT PROFILE. Fix mismatches. Fill empty fields.
9. Answer screening questions using the rules above. VERIFY after screening fields.
10. {submit_instruction}
11. After submit: browser_snapshot. If the page asks for an email/security/verification code, follow EMAIL VERIFICATION immediately.{" Run CAPTCHA DETECT if submit seems blocked." if captcha_section else ""} Then check for new tabs (browser_tabs action: "list"). Switch to newest, close old. Snapshot to confirm submission. Look for "thank you" or "application received".
12. Output your result.

{email_verification_section}

{pacing_section}

== MANDATORY FINAL LINE ==
Your very last line MUST be ONE of:

  RESULT_JSON:{{"status":"applied",        "submit_click_ref":"...", "submit_button_text":"...",
               "pre_submit_url":"...",    "post_submit_url":"...",  "post_submit_snapshot":{{...}},
               "confirmation_copy":"...", "screenshot_path":"...", "verification_code_used":"...",
               "company_apply_url":"..." }}
  RESULT_JSON:{{"status":"dry_run",        "would_click_ref":"...",  "would_click_text":"..."}}
  RESULT_JSON:{{"status":"failed",         "reason":"<short>"}}
  RESULT_JSON:{{"status":"captcha"}}        | "login_issue" | "expired" | "pause_for_human"

If you cannot produce a status:"applied" JSON because you did not actually click Submit
and observe a post-submit state, you MUST emit status:"dry_run" or status:"failed".
Do NOT emit status:"applied" otherwise. The system will REJECT and DOWNGRADE any
"applied" record that lacks submit_click_ref, post_submit_url, or post_submit_snapshot.

Deprecated (do not use): legacy freeform RESULT: lines such as RESULT:APPLIED, RESULT:EXPIRED,
RESULT:CAPTCHA, RESULT:LOGIN_ISSUE, RESULT:FAILED:reason — use RESULT_JSON instead.

{page_grounding_section}

{ats_form_repair_section}

{form_verify_section}

== FORM TRICKS ==
- Popup/new window opened? browser_tabs action "list" to see all tabs. browser_tabs action "select" with the tab index to switch. ALWAYS check for new tabs after clicking login/apply/sign-in buttons.
- "Upload your resume" pre-fill page (Workday, Lever, etc.): This is NOT the application form yet. Click "Select file" or the upload area, then browser_file_upload with the resume PDF path. Wait for parsing to finish. Then click Next/Continue to reach the actual form.
- File upload not working? Try: (1) browser_click the upload button/area, (2) browser_file_upload with the path. If still failing, look for a hidden file input or a "Select file" link and click that first.
- Dropdown won't fill? browser_click to open it, then browser_click the option.
- Checkbox won't check via fill_form? Use browser_click on it instead. Snapshot to verify.
- Phone field with country prefix: just type digits {phone_digits}
- Date fields: {datetime.now().strftime('%m/%d/%Y')}
- Validation errors after submit? browser_snapshot, run VERIFY PAGE STATE (read visibleErrors), fix all, retry.
- Before clicking Next on multi-page forms: VERIFY must show no visibleErrors and no unexpected emptyRequired fields.
- Honeypot fields (hidden, "leave blank"): skip them.
- Format-sensitive fields: read the placeholder text, match it exactly.

{captcha_section}

== WHEN TO GIVE UP ==
- Same page after 3 attempts with no progress -> RESULT:FAILED:stuck
- Job is closed/expired/page says "no longer accepting" -> RESULT:EXPIRED
- Page is broken/500 error/blank -> RESULT:FAILED:page_error
Stop immediately. Output your RESULT_JSON final line. Do not loop.

Do not end the session without the RESULT_JSON final line. No summary text after it."""

    return prompt
