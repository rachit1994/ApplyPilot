"""LinkedIn India harvester — turn LinkedIn listings into company apply URLs.

Strategy (low ban risk):
  * You log into LinkedIn once in a visible, persistent-profile Chrome.
  * We search India jobs, open each, and click the real "Apply" button.
  * LinkedIn does NOT expose the external apply link in the DOM, so the click
    opens the employer's site in a new tab; we read that tab's final (redirected)
    URL and store ONLY that company/ATS URL — never the linkedin.com URL.
  * For every company we touch, we also enumerate the company's other open India
    roles and capture their apply URLs too.

The captured company URLs then flow to the existing deterministic Direct Apply
engine (``applypilot apply --deterministic-only``), which fills+submits on the
employer's own form with zero Claude. Greenhouse/Ashby are excluded by config.

This module splits into pure, unit-tested helpers (URL/location logic) and the
live browser-driving functions (run against your logged-in Chrome).
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote_plus,
    urlencode,
    unquote,
    urljoin,
    urlsplit,
    urlunsplit,
)

logger = logging.getLogger(__name__)

# LinkedIn geoId for "India". Used to constrain search + company listings.
INDIA_GEO_ID = "102713980"

# India location tokens — a captured job whose location matches none of these is
# dropped (we only want India openings).
_INDIA_LOCATION_TOKENS: tuple[str, ...] = (
    "india", "bengaluru", "bangalore", "karnataka", "hyderabad", "telangana",
    "pune", "maharashtra", "mumbai", "navi mumbai", "thane", "chennai",
    "tamil nadu", "delhi", "new delhi", "ncr", "noida", "gurgaon", "gurugram",
    "faridabad", "ghaziabad", "kolkata", "west bengal", "ahmedabad", "gujarat",
    "jaipur", "rajasthan", "kochi", "kerala", "coimbatore", "indore",
    "chandigarh", "bhubaneswar", "nagpur", "remote, india", "india (remote)",
)

_SLUG_RE = re.compile(r"/company/([^/?#]+)", re.I)
_LINKEDIN_JOB_ID_RE = re.compile(r"(?:/jobs/view/|currentJobId=|jobId=)(\d+)", re.I)

_ROLE_RELEVANCE_TOKENS: tuple[str, ...] = (
    "software",
    "engineer",
    "developer",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "full stack",
    "full-stack",
    "web",
    "platform",
    "staff",
    "principal",
    "lead",
)

_KNOWN_JOB_HOST_TOKENS: tuple[str, ...] = (
    "ashbyhq.com",
    "greenhouse.io",
    "jobs.lever.co",
    "lever.co",
    "myworkdayjobs.com",
    "workdayjobs.com",
    "mokahr.com",
    "kula.ai",
)

_LINKEDIN_PAGE_DELAY_MS = (3500, 7000)
_LINKEDIN_CARD_CLICK_DELAY_MS = (2200, 5200)
_LINKEDIN_APPLY_CLICK_DELAY_MS = (3000, 6500)
_LINKEDIN_MAX_LISTING_PAGES = 5

_LINKEDIN_BLOCK_URL_TOKENS: tuple[str, ...] = (
    "/authwall",
    "/checkpoint",
    "/login",
    "/uas/login",
    "/signup",
)

_LINKEDIN_BLOCK_TEXT_TOKENS: tuple[str, ...] = (
    "sign in",
    "join linkedin",
    "login to linkedin",
    "security verification",
    "security check",
    "verify that you",
    "verify you are",
    "are you a human",
    "unusual activity",
    "captcha",
    "checkpoint",
    "temporarily restricted",
    "automated queries",
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def build_search_url(keywords: str, *, start: int = 0, geo_id: str = INDIA_GEO_ID) -> str:
    """LinkedIn jobs search URL, India-scoped, paginated by ``start`` (25/page)."""
    kw = quote_plus((keywords or "").strip())
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={kw}&geoId={geo_id}&location=India&start={max(0, int(start))}"
    )


def page_url_with_start(url: str, start: int) -> str:
    """Return a LinkedIn listing URL with the requested pagination offset."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "start"]
    query.append(("start", str(max(0, int(start)))))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def linkedin_job_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _LINKEDIN_JOB_ID_RE.search(unquote(url))
    return match.group(1) if match else None


def company_name_from_slug(slug: str) -> str:
    """Best-effort readable company name from a LinkedIn slug (acme-india -> acme india)."""
    return re.sub(r"[-_]+", " ", (slug or "").strip()).strip()


def company_jobs_url(slug: str, *, geo_id: str = INDIA_GEO_ID) -> str:
    """India-scoped jobs listing for one company, via name search (reliable pagination)."""
    return build_search_url(company_name_from_slug(slug), geo_id=geo_id)


def is_linkedin_url(url: str | None) -> bool:
    if not url:
        return False
    return "linkedin.com" in urlsplit(url).netloc.lower()


def linkedin_block_reason(url: str | None, text: str | None = None) -> str | None:
    """Return a manual-clear reason when LinkedIn is blocking automation."""
    parts = urlsplit(url or "")
    host = parts.netloc.lower()
    path = parts.path.lower()
    query = parts.query.lower()
    blob = re.sub(r"\s+", " ", text or "").strip().lower()
    if "linkedin.com" not in host:
        return None
    if any(tok in path for tok in _LINKEDIN_BLOCK_URL_TOKENS):
        if "checkpoint" in path:
            return "linkedin_checkpoint"
        if "authwall" in path:
            return "linkedin_authwall"
        if "signup" in path:
            return "linkedin_signup_wall"
        return "linkedin_login_required"
    if "trk=public_jobs" in query and "authwall" in query:
        return "linkedin_authwall"
    if any(tok in blob for tok in _LINKEDIN_BLOCK_TEXT_TOKENS):
        if "captcha" in blob or "human" in blob or "security" in blob or "unusual activity" in blob:
            return "linkedin_bot_or_security_check"
        return "linkedin_login_required"
    return None


def extract_linkedin_redirect_target(url: str | None) -> str | None:
    """Unwrap a linkedin.com/redir/redirect?url=<encoded> interstitial, else None."""
    if not url:
        return None
    parts = urlsplit(url)
    if "linkedin.com" not in parts.netloc.lower():
        return None
    qs = parse_qs(parts.query)
    for key in ("url", "originalReferer", "redirect"):
        vals = qs.get(key)
        if vals and vals[0].strip():
            target = unquote(vals[0]).strip()
            if target.startswith(("http://", "https://")) and not is_linkedin_url(target):
                return target
    return None


def clean_redirect_url(url: str | None) -> str | None:
    """Return the external employer URL, or None if it never left LinkedIn.

    Handles the ``/redir/redirect?url=`` interstitial. A URL still on linkedin.com
    after unwrapping means the click did not produce an external apply page
    (e.g. Easy Apply or a login wall) — we drop it rather than store a junk row.
    """
    if not url:
        return None
    url = url.strip()
    if is_linkedin_url(url):
        return extract_linkedin_redirect_target(url)
    if url.startswith(("http://", "https://")):
        return url
    return None


def is_probable_intermediate_apply_url(url: str | None) -> bool:
    """True for detail/marketing pages that often still need an Apply click."""
    if not url:
        return False
    parts = urlsplit(url)
    path = parts.path.lower()
    query = parts.query.lower()
    if "job_app" in path or "/apply" in path or "application" in path:
        return False
    if any(key in query for key in ("gh_jid=", "lever-source=", "jobid=", "job_id=")):
        return True
    return any(tok in path for tok in ("/job/", "/jobs/", "/careers/", "/positions/"))


def looks_like_india(location_text: str | None) -> bool:
    if not location_text:
        return False
    blob = location_text.lower()
    return any(tok in blob for tok in _INDIA_LOCATION_TOKENS)


def looks_role_relevant(text: str | None) -> bool:
    if not text:
        return False
    blob = re.sub(r"\s+", " ", text).strip().lower()
    return any(tok in blob for tok in _ROLE_RELEVANCE_TOKENS)


def same_host_or_subdomain(url: str | None, base_url: str | None) -> bool:
    if not url or not base_url:
        return False
    host = urlsplit(url).netloc.lower().split(":")[0]
    base = urlsplit(base_url).netloc.lower().split(":")[0]
    if not host or not base:
        return False
    if host == base:
        return True
    return host.endswith("." + base) or base.endswith("." + host)


def is_known_job_host(url: str | None) -> bool:
    if not url:
        return False
    host = urlsplit(url).netloc.lower().split(":")[0]
    return any(tok in host for tok in _KNOWN_JOB_HOST_TOKENS)


def company_slug_from_url(url: str | None) -> str | None:
    """Pull the company slug from a linkedin.com/company/<slug> URL."""
    if not url:
        return None
    m = _SLUG_RE.search(url)
    return m.group(1).strip().lower() if m else None


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def delay_ms(bounds: tuple[int, int]) -> int:
    lo, hi = bounds
    lo = max(0, int(lo))
    hi = max(lo, int(hi))
    return random.randint(lo, hi)


def listing_page_budget(max_jobs: int) -> int:
    # `max_jobs` counts captured form URLs, not LinkedIn cards visited. Keep a
    # separate page cap so skipped jobs cannot create an unbounded LinkedIn crawl.
    try:
        jobs = max(1, int(max_jobs))
    except (TypeError, ValueError):
        jobs = 1
    return max(1, min(_LINKEDIN_MAX_LISTING_PAGES, (jobs + 4) // 5))


# ---------------------------------------------------------------------------
# Persistence (bypasses the US-centric discover filter on purpose)
# ---------------------------------------------------------------------------

def store_harvested_jobs(jobs: list[dict[str, Any]]) -> dict[str, int]:
    """Insert harvested India rows keyed by the company/ATS URL (not LinkedIn).

    Uses INSERT OR IGNORE on the ``url`` primary key so re-running is idempotent
    and a company's role seen via search + company-expansion de-dupes cleanly.
    """
    from datetime import datetime, timezone

    from applypilot.database import ensure_columns, get_connection

    conn = get_connection()
    ensure_columns(conn)
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    dup = 0
    for job in jobs:
        # Prefer the resolved form URL over the employer landing/detail page.
        url = (job.get("application_url") or job.get("url") or "").strip()
        if not url or is_linkedin_url(url):
            continue
        # The jobs table has no `company` column; keep the company name in the
        # description text so scoring/tailoring still see it.
        company = (job.get("company") or "").strip()
        desc = (job.get("full_description") or job.get("description") or "").strip()
        full_description = (f"Company: {company}\n{desc}".strip() if company else desc) or None
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (url, title, site, strategy, location,
                 application_url, full_description, discovered_at)
            VALUES (?, ?, 'LinkedIn->Company', 'linkedin_external', ?, ?, ?, ?)
            """,
            (
                url,
                job.get("title"),
                job.get("location"),
                job.get("application_url") or url,
                full_description,
                now,
            ),
        )
        if cur.rowcount:
            new += 1
        else:
            dup += 1
    conn.commit()
    return {"new": new, "duplicate": dup, "seen": len(jobs)}


# ---------------------------------------------------------------------------
# Live browser driving (run against your logged-in Chrome over CDP)
# ---------------------------------------------------------------------------

# Selectors are centralized so they can be retuned in one place after a live run
# (LinkedIn A/B-tests its DOM). Each entry is tried in order.
_SEL = {
    "job_card": [
        "div.job-card-container",
        "li.jobs-search-results__list-item",
        "div.jobs-search-results-list__list-item",
    ],
    "title": [
        "h1.job-details-jobs-unified-top-card__job-title",
        ".job-details-jobs-unified-top-card__job-title",
        "h1",
    ],
    "company": [
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
    ],
    "location": [
        ".job-details-jobs-unified-top-card__primary-description-container",
        ".job-details-jobs-unified-top-card__tertiary-description-container",
    ],
    "apply_button": [
        "button.jobs-apply-button",
        ".jobs-s-apply button",
        "button[aria-label*='Apply']",
    ],
    "continue_in_modal": [
        "button:has-text('Continue')",
        "a:has-text('Continue')",
    ],
    "logged_in_marker": [
        "img.global-nav__me-photo",
        "div.global-nav__me",
        "a[href*='/feed']",
    ],
}

_EMPLOYER_APPLY_TEXTS: tuple[str, ...] = (
    "apply now",
    "apply for this job",
    "apply to this job",
    "apply for this position",
    "start application",
    "start your application",
    "apply",
)

_EMPLOYER_APPLY_HREF_SELECTORS: tuple[str, ...] = (
    "a[href*='job_app']",
    "a[href*='/apply']",
    "a[href*='application']",
    "a[href*='job-application']",
    "a[href*='myworkdayjobs']",
)

_EMPLOYER_ALL_JOBS_TEXTS: tuple[str, ...] = (
    "all jobs",
    "all open roles",
    "all openings",
    "back to jobs",
    "back to careers",
    "back to openings",
    "browse jobs",
    "browse open roles",
    "view all jobs",
    "view all openings",
    "see all jobs",
    "see open roles",
    "search jobs",
)

_EMPLOYER_JOB_LINK_SELECTORS: tuple[str, ...] = (
    "a[href*='/job']",
    "a[href*='/jobs']",
    "a[href*='/careers']",
    "a[href*='/position']",
    "a[href*='/opening']",
    "a[href*='myworkdayjobs']",
    "a[href*='greenhouse.io']",
    "a[href*='ashbyhq.com']",
    "a[href*='lever.co']",
)


def open_login_browser(worker_id: int = 0) -> int:
    """Launch the visible persistent-profile Chrome and open LinkedIn login.

    Leaves Chrome running (own process session) so you can log in by hand; the
    session persists in the worker profile and is reused by harvest + apply.
    Returns the CDP port.
    """
    from applypilot.apply import chrome
    from applypilot.apply.chrome import BASE_CDP_PORT

    port = BASE_CDP_PORT + worker_id
    chrome.launch_chrome(worker_id, port=port, headless=False)
    pw, browser, context = connect_cdp(port)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(
                "https://www.linkedin.com/login",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        # Detach Playwright but leave the externally-launched Chrome open.
        try:
            pw.stop()
        except Exception:  # noqa: BLE001
            pass
    return port


def connect_cdp(port: int):
    """Attach Playwright to a Chrome already listening on a CDP ``port``.

    Returns (playwright, browser, context). Reuses the existing logged-in
    context so the LinkedIn session is shared with Direct Apply.
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=20_000)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    return pw, browser, context


def _first(page, kind: str):
    for sel in _SEL[kind]:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:  # noqa: BLE001
            continue
    return None


def _text(page, kind: str) -> str:
    loc = _first(page, kind)
    if loc is None:
        return ""
    try:
        return (loc.inner_text(timeout=4000) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _visible_application_field_count(page) -> int:
    try:
        return int(
            page.eval_on_selector_all(
                "input:not([type=hidden]), textarea, select",
                """
                els => els.filter(el => {
                    const style = window.getComputedStyle(el);
                    const box = el.getBoundingClientRect();
                    return style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && box.width > 0
                        && box.height > 0;
                }).length
                """,
            )
        )
    except Exception:  # noqa: BLE001
        return 0


def _looks_like_form_page(page) -> bool:
    if _visible_application_field_count(page) < 3:
        return False
    try:
        body = (page.inner_text("body", timeout=3000) or "").lower()
    except Exception:  # noqa: BLE001
        body = ""
    return any(tok in body for tok in ("resume", "cv", "submit application", "application"))


def _absolute_href(page, locator) -> str | None:
    try:
        href = locator.get_attribute("href", timeout=2000)
    except Exception:  # noqa: BLE001
        return None
    if not href or href.startswith(("javascript:", "#", "mailto:")):
        return None
    return urljoin(page.url, href)


def _employer_apply_controls(page):
    """Yield likely employer-side Apply controls, links before buttons."""
    yielded = 0
    for sel in _EMPLOYER_APPLY_HREF_SELECTORS:
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 5)
        except Exception:  # noqa: BLE001
            count = 0
        for idx in range(count):
            yielded += 1
            yield loc.nth(idx)
    for text in _EMPLOYER_APPLY_TEXTS:
        for role in ("link", "button"):
            try:
                loc = page.get_by_role(role, name=text, exact=False)
                count = min(loc.count(), 5)
            except Exception:  # noqa: BLE001
                count = 0
            for idx in range(count):
                yielded += 1
                yield loc.nth(idx)
    if yielded == 0:
        return


def _employer_all_jobs_controls(page):
    for text in _EMPLOYER_ALL_JOBS_TEXTS:
        for role in ("link", "button"):
            try:
                loc = page.get_by_role(role, name=text, exact=False)
                count = min(loc.count(), 4)
            except Exception:  # noqa: BLE001
                count = 0
            for idx in range(count):
                yield loc.nth(idx)


def _link_text(locator) -> str:
    try:
        return (locator.inner_text(timeout=1500) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _paced_wait(page, bounds: tuple[int, int]) -> None:
    try:
        page.wait_for_timeout(delay_ms(bounds))
    except Exception:  # noqa: BLE001
        pass


def _linkedin_block_reason_for_page(page) -> str | None:
    try:
        url = page.url
    except Exception:  # noqa: BLE001
        url = ""
    text = ""
    if is_linkedin_url(url):
        try:
            text = page.inner_text("body", timeout=2_000) or ""
        except Exception:  # noqa: BLE001
            text = ""
    return linkedin_block_reason(url, text)


def _wait_for_user_to_clear_linkedin_block(
    page,
    *,
    resume_url: str | None = None,
    timeout_s: float = 900.0,
) -> bool:
    """Pause for manual login/CAPTCHA/security clear, then verify before continuing."""
    reason = _linkedin_block_reason_for_page(page)
    if not reason:
        return True

    print(
        "\n>>> LinkedIn is blocking harvest "
        f"({reason}). Fix it in the opened Chrome window, then press Enter here. "
        "I will verify the block is gone before continuing.",
        flush=True,
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            input(">>> Press Enter after clearing LinkedIn login/security check: ")
        except EOFError:
            time.sleep(5)
        except KeyboardInterrupt:
            raise

        try:
            if resume_url and not _linkedin_block_reason_for_page(page):
                page.goto(resume_url, wait_until="domcontentloaded", timeout=30_000)
                _paced_wait(page, _LINKEDIN_PAGE_DELAY_MS)
        except Exception:  # noqa: BLE001
            pass

        reason = _linkedin_block_reason_for_page(page)
        if not reason:
            print(">>> LinkedIn block cleared. Continuing harvest.\n", flush=True)
            return True
        print(f">>> Still blocked ({reason}). Clear it in Chrome and press Enter again.", flush=True)

    print(">>> Timed out waiting for LinkedIn block to clear.", flush=True)
    return False


def _candidate_company_job_links(page, *, base_url: str, limit: int) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for sel in _EMPLOYER_JOB_LINK_SELECTORS:
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 80)
        except Exception:  # noqa: BLE001
            count = 0
        for idx in range(count):
            link = loc.nth(idx)
            href = _absolute_href(page, link)
            cleaned = clean_redirect_url(href)
            if not cleaned or cleaned in seen or is_linkedin_url(cleaned):
                continue
            if not same_host_or_subdomain(cleaned, base_url) and not is_known_job_host(cleaned):
                continue
            label = _link_text(link)
            signal = f"{label} {cleaned}"
            if not looks_role_relevant(signal):
                continue
            # If the listing text exposes a location, keep India-focused rows.
            # If it does not, allow it and let later apply-time checks decide.
            if any(tok in signal.lower() for tok in ("remote", "india", "bengaluru", "bangalore", "hyderabad", "pune", "gurgaon", "gurugram", "chennai")):
                if not looks_like_india(signal):
                    continue
            seen.add(cleaned)
            candidates.append({"url": cleaned, "title": label})
            if len(candidates) >= limit:
                return candidates
    return candidates


def _discover_employer_sibling_jobs(
    context,
    url: str,
    *,
    company: str | None,
    location: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Use employer-side All Jobs / Back to Jobs links to find sibling roles."""
    if limit <= 0:
        return []
    target = clean_redirect_url(url)
    if not target:
        return []
    page = context.new_page()
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=18_000)
        page.wait_for_timeout(800)
        listing_pages: list[str] = []
        for ctrl in _employer_all_jobs_controls(page):
            href = _absolute_href(page, ctrl)
            if href:
                cleaned = clean_redirect_url(href)
                if cleaned and not is_linkedin_url(cleaned):
                    listing_pages.append(cleaned)
                    continue
            before = page.url
            try:
                ctrl.click(timeout=3_000)
                page.wait_for_timeout(1_500)
            except Exception:  # noqa: BLE001
                continue
            after = clean_redirect_url(page.url)
            if after and after != before:
                listing_pages.append(after)
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=12_000)
                    page.wait_for_timeout(500)
                except Exception:  # noqa: BLE001
                    break
        if not listing_pages:
            # Some career pages are already the listing page or expose related
            # roles directly below the job detail.
            listing_pages.append(page.url)

        jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for listing_url in dedupe_preserve_order(listing_pages):
            try:
                page.goto(listing_url, wait_until="domcontentloaded", timeout=18_000)
                page.wait_for_timeout(1_200)
            except Exception:  # noqa: BLE001
                continue
            for cand in _candidate_company_job_links(page, base_url=target, limit=limit * 2):
                if len(jobs) >= limit:
                    return jobs
                candidate_url = cand["url"]
                if candidate_url in seen_urls:
                    continue
                seen_urls.add(candidate_url)
                form_url, reason = _resolve_employer_form_url(context, candidate_url)
                if not form_url:
                    logger.info("Skip sibling (%s): %s", reason, candidate_url[:70])
                    continue
                if form_url in seen_urls:
                    continue
                seen_urls.add(form_url)
                title = cand.get("title") or "Role"
                jobs.append(
                    {
                        "url": form_url,
                        "application_url": form_url,
                        "title": title,
                        "company": company,
                        "location": location or "India",
                        "description": f"Sibling role found via employer all-jobs page: {candidate_url}",
                    }
                )
                logger.info("Captured sibling: %s @ %s -> %s", title[:40], (company or "")[:30], form_url[:60])
        return jobs
    except Exception as exc:  # noqa: BLE001
        logger.debug("Employer sibling discovery failed for %s: %s", target[:80], exc)
        return []
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass


def _settle_form_url(page) -> str | None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8_000)
        try:
            page.wait_for_load_state("networkidle", timeout=2_500)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    return clean_redirect_url(page.url)


def _resolve_employer_form_url(context, url: str) -> tuple[str | None, str]:
    """Open an employer page, click its own Apply control, return exact form URL."""
    target = clean_redirect_url(url)
    if not target:
        return None, "no_external_target"
    page = context.new_page()
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=18_000)
        page.wait_for_timeout(1_000)
        if _looks_like_form_page(page):
            return _settle_form_url(page), "already_form"

        attempts = 0
        for ctrl in _employer_apply_controls(page):
            attempts += 1
            if attempts > 8:
                break
            href = _absolute_href(page, ctrl)
            if href:
                cleaned = clean_redirect_url(href)
                if cleaned and not is_linkedin_url(cleaned):
                    page.goto(cleaned, wait_until="domcontentloaded", timeout=18_000)
                    page.wait_for_timeout(1_000)
                    final_url = _settle_form_url(page)
                    if final_url and (
                        _looks_like_form_page(page)
                        or not is_probable_intermediate_apply_url(final_url)
                    ):
                        return final_url, "href_apply"
                    page.goto(target, wait_until="domcontentloaded", timeout=18_000)
                    page.wait_for_timeout(500)
                    continue

            before = page.url
            popup = None
            try:
                with context.expect_page(timeout=3_000) as pinfo:
                    ctrl.click(timeout=4_000)
                popup = pinfo.value
            except Exception:  # noqa: BLE001
                popup = None
            if popup is not None:
                try:
                    final_url = _settle_form_url(popup)
                finally:
                    try:
                        popup.close()
                    except Exception:  # noqa: BLE001
                        pass
                if final_url and not is_probable_intermediate_apply_url(final_url):
                    return final_url, "popup_apply"
            else:
                page.wait_for_timeout(2_000)
                final_url = _settle_form_url(page)
                if final_url and final_url != before:
                    return final_url, "same_tab_apply"
        final_url = _settle_form_url(page)
        if final_url and _looks_like_form_page(page):
            return final_url, "form_after_load"
        return None, "no_employer_form_url"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Employer form URL resolution failed for %s: %s", target[:80], exc)
        return None, "employer_resolution_error"
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass


def is_logged_in(page) -> bool:
    for sel in _SEL["logged_in_marker"]:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return "linkedin.com/feed" in page.url


def wait_until_logged_in(page, *, timeout_s: float = 300.0) -> bool:
    """Open LinkedIn and block until the user has logged in (manual)."""
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30_000)
    except Exception:  # noqa: BLE001
        pass
    print("\n>>> Log into LinkedIn in the opened Chrome window. Waiting…", flush=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        reason = _linkedin_block_reason_for_page(page)
        if reason:
            if not _wait_for_user_to_clear_linkedin_block(
                page,
                resume_url="https://www.linkedin.com/feed/",
                timeout_s=max(1.0, deadline - time.time()),
            ):
                return False
        if is_logged_in(page):
            print(">>> LinkedIn login detected. Continuing.\n", flush=True)
            return True
        time.sleep(3)
    print(">>> Timed out waiting for login.", flush=True)
    return False


def _capture_external_apply_url(context, page) -> tuple[str | None, str]:
    """Click Apply and return (external_url, reason).

    Skips Easy Apply (on-LinkedIn, login flow). For external Apply, captures the
    new tab's final URL after redirects and returns the employer URL.
    """
    if not _wait_for_user_to_clear_linkedin_block(page, resume_url=page.url):
        return None, "linkedin_block_timeout"
    btn = _first(page, "apply_button")
    if btn is None:
        return None, "no_apply_button"
    try:
        label = (btn.inner_text(timeout=3000) or "").strip().lower()
    except Exception:  # noqa: BLE001
        label = ""
    if "easy apply" in label:
        return None, "easy_apply"
    _paced_wait(page, _LINKEDIN_APPLY_CLICK_DELAY_MS)

    def _grab_new_tab(click_target) -> str | None:
        try:
            with context.expect_page(timeout=15_000) as pinfo:
                click_target.click(timeout=8000)
            popup = pinfo.value
        except Exception:  # noqa: BLE001
            return None
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=20_000)
            try:
                popup.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            url = popup.url
        finally:
            try:
                popup.close()
            except Exception:  # noqa: BLE001
                pass
        return url

    url = _grab_new_tab(btn)
    # Some flows interpose a "Continue" leave-LinkedIn modal that opens the tab.
    if url is None:
        cont = _first(page, "continue_in_modal")
        if cont is not None:
            url = _grab_new_tab(cont)
    if url is None:
        return None, "no_new_tab"
    target = clean_redirect_url(url)
    if not target:
        return None, "no_external_redirect"
    form_url, form_reason = _resolve_employer_form_url(context, target)
    if form_url:
        return form_url, "ok"
    if is_probable_intermediate_apply_url(target):
        return None, form_reason
    return target, "ok"


def _job_cards(page):
    for sel in _SEL["job_card"]:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                return loc
        except Exception:  # noqa: BLE001
            continue
    return page.locator("div.job-card-container")


def _card_key(card) -> str:
    for attr in ("data-job-id", "data-occludable-job-id", "href"):
        try:
            val = card.get_attribute(attr, timeout=1000)
        except Exception:  # noqa: BLE001
            val = None
        if val:
            job_id = linkedin_job_id_from_url(val)
            return f"job:{job_id}" if job_id else f"{attr}:{val.strip()}"
    try:
        links = card.locator("a[href*='/jobs/view/'], a[href*='currentJobId=']")
        count = min(links.count(), 3)
    except Exception:  # noqa: BLE001
        count = 0
    for idx in range(count):
        try:
            href = links.nth(idx).get_attribute("href", timeout=1000)
        except Exception:  # noqa: BLE001
            href = None
        job_id = linkedin_job_id_from_url(href)
        if job_id:
            return f"job:{job_id}"
    try:
        text = re.sub(r"\s+", " ", (card.inner_text(timeout=1500) or "")).strip()
        return "text:" + text[:200] if text else ""
    except Exception:  # noqa: BLE001
        return ""


def _page_card_signature(cards, count: int) -> tuple[str, ...]:
    keys: list[str] = []
    for idx in range(count):
        try:
            key = _card_key(cards.nth(idx))
        except Exception:  # noqa: BLE001
            key = ""
        if key:
            keys.append(key)
    return tuple(keys)


def harvest_listing(
    context,
    list_url: str,
    *,
    max_jobs: int,
    max_employer_jobs: int = 0,
) -> tuple[list[dict], list[str]]:
    """Harvest one LinkedIn listing page set; returns (jobs, company_slugs)."""
    pages = context.pages
    page = pages[0] if pages else context.new_page()
    jobs: list[dict] = []
    slugs: list[str] = []
    seen_cards: set[str] = set()
    seen_apply_urls: set[str] = set()
    seen_page_signatures: set[tuple[str, ...]] = set()
    max_pages = listing_page_budget(max_jobs)
    pages_scanned = 0
    start = 0
    while len(jobs) < max_jobs and pages_scanned < max_pages:
        url = page_url_with_start(list_url, start)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            _paced_wait(page, _LINKEDIN_PAGE_DELAY_MS)
        except Exception:  # noqa: BLE001
            break
        if not _wait_for_user_to_clear_linkedin_block(page, resume_url=url):
            break
        pages_scanned += 1
        cards = _job_cards(page)
        n = cards.count()
        if n == 0:
            break
        page_signature = _page_card_signature(cards, min(n, 25))
        if not page_signature:
            logger.info("Stopping listing pagination: no stable card keys at start=%s", start)
            break
        if page_signature in seen_page_signatures:
            logger.info("Stopping listing pagination: repeated page signature at start=%s", start)
            break
        seen_page_signatures.add(page_signature)
        unseen_on_page = 0
        for i in range(n):
            if len(jobs) >= max_jobs:
                break
            try:
                key = _card_key(cards.nth(i))
            except Exception:  # noqa: BLE001
                key = ""
            if not key:
                continue
            if key in seen_cards:
                continue
            seen_cards.add(key)
            unseen_on_page += 1
            try:
                _paced_wait(page, _LINKEDIN_CARD_CLICK_DELAY_MS)
                cards.nth(i).click(timeout=6000)
                _paced_wait(page, _LINKEDIN_CARD_CLICK_DELAY_MS)
                if _linkedin_block_reason_for_page(page):
                    if not _wait_for_user_to_clear_linkedin_block(page, resume_url=url):
                        return jobs, dedupe_preserve_order(slugs)
                    cards = _job_cards(page)
                    if i >= cards.count():
                        continue
                    _paced_wait(page, _LINKEDIN_CARD_CLICK_DELAY_MS)
                    cards.nth(i).click(timeout=6000)
                    _paced_wait(page, _LINKEDIN_CARD_CLICK_DELAY_MS)
                    if _linkedin_block_reason_for_page(page):
                        continue
            except Exception:  # noqa: BLE001
                continue
            title = _text(page, "title")
            company = _text(page, "company")
            location = _text(page, "location")
            if not looks_like_india(location):
                continue
            comp_loc = _first(page, "company")
            try:
                href = comp_loc.get_attribute("href") if comp_loc else None
            except Exception:  # noqa: BLE001
                href = None
            slug = company_slug_from_url(href)
            if slug:
                slugs.append(slug)
            apply_url, reason = _capture_external_apply_url(context, page)
            if apply_url:
                if apply_url in seen_apply_urls:
                    continue
                seen_apply_urls.add(apply_url)
                job = {
                    "url": apply_url,
                    "application_url": apply_url,
                    "title": title or "Role",
                    "company": company or None,
                    "location": location or "India",
                }
                jobs.append(job)
                logger.info("Captured: %s @ %s -> %s", title[:40], company[:30], apply_url[:60])
                if max_employer_jobs > 0 and len(jobs) < max_jobs:
                    siblings = _discover_employer_sibling_jobs(
                        context,
                        apply_url,
                        company=company or None,
                        location=location or "India",
                        limit=min(max_employer_jobs, max_jobs - len(jobs)),
                    )
                    for sibling in siblings:
                        sibling_url = sibling.get("application_url") or sibling.get("url")
                        if not sibling_url or sibling_url in seen_apply_urls:
                            continue
                        seen_apply_urls.add(sibling_url)
                        jobs.append(sibling)
                        if len(jobs) >= max_jobs:
                            break
            else:
                logger.info("Skip (%s): %s @ %s", reason, title[:40], company[:30])
        if unseen_on_page == 0:
            logger.info("Stopping listing pagination: page repeated at start=%s", start)
            break
        start += 25
    if pages_scanned >= max_pages and len(jobs) < max_jobs:
        logger.info("Stopping listing pagination: page budget reached (%s pages)", max_pages)
    return jobs, dedupe_preserve_order(slugs)


def run_harvest(
    *,
    keywords: str,
    max_jobs: int = 25,
    expand_company: bool = True,
    max_company_jobs: int = 15,
    expand_employer: bool = True,
    max_employer_jobs: int = 5,
    worker_id: int = 0,
) -> dict[str, Any]:
    """End-to-end: launch logged-in Chrome, harvest India jobs + company roles, store.

    Launches the visible persistent-profile Chrome (same one Direct Apply uses),
    waits for you to log into LinkedIn, then harvests.
    """
    from applypilot.apply import chrome
    from applypilot.apply.chrome import BASE_CDP_PORT
    from applypilot.database import init_db

    init_db()
    port = BASE_CDP_PORT + worker_id
    proc = chrome.launch_chrome(worker_id, port=port, headless=False)
    pw = browser = context = None
    try:
        pw, browser, context = connect_cdp(port)
        page = context.pages[0] if context.pages else context.new_page()
        if not wait_until_logged_in(page):
            return {"error": "login_timeout"}

        jobs, slugs = harvest_listing(
            context,
            build_search_url(keywords),
            max_jobs=max_jobs,
            max_employer_jobs=max_employer_jobs if expand_employer else 0,
        )
        if expand_company:
            for slug in slugs:
                more, _ = harvest_listing(
                    context,
                    company_jobs_url(slug),
                    max_jobs=max_company_jobs,
                    max_employer_jobs=max_employer_jobs if expand_employer else 0,
                )
                jobs.extend(more)

        # De-dupe by captured URL before storing.
        seen: set[str] = set()
        unique = []
        for j in jobs:
            if j["url"] not in seen:
                seen.add(j["url"])
                unique.append(j)
        result = store_harvested_jobs(unique)
        result["companies_expanded"] = len(slugs)
        return result
    finally:
        try:
            if context is not None:
                # leave the browser open so Direct Apply can reuse the session
                pass
            if pw is not None:
                pw.stop()
        except Exception:  # noqa: BLE001
            pass
        # NOTE: we intentionally do NOT kill Chrome here — the logged-in profile
        # stays available for `applypilot apply --deterministic-only`.
        _ = proc
