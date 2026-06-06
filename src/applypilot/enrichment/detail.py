"""Detail page enrichment: scrapes full descriptions and apply URLs.

For each job URL in the database, navigates to the detail page and extracts:
  - full_description: the complete job posting text
  - application_url: the "Apply" button/link URL

Three-tier extraction cascade (cheapest first):
  Tier 1: JSON-LD JobPosting structured data (0 tokens)
  Tier 2: Deterministic CSS pattern matching (0 tokens)
  Tier 3: LLM-assisted extraction (1 LLM call)
"""

import json
import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, unquote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from applypilot import config
from applypilot.config import DB_PATH
from applypilot.database import get_connection, init_db
from applypilot.enrichment.pending import (
    DETAIL_GOTO_ATTEMPTS,
    detail_pending_clause,
    persist_detail_scrape_result,
)
from applypilot.llm import get_client

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Sites that block scraping -- skip detail extraction entirely
SKIP_DETAIL_SITES = {"glassdoor", "google", "Workopolis"}

# Module-level proxy config (set from CLI or caller)
_PROXY_CONFIG: dict | None = None


def set_proxy(proxy_str: str | None):
    """Set proxy config from an external caller."""
    global _PROXY_CONFIG
    if proxy_str:
        from applypilot.discovery.jobspy import parse_proxy
        _PROXY_CONFIG = parse_proxy(proxy_str)


# -- URL resolution ----------------------------------------------------------

def _load_base_urls() -> dict[str, str | None]:
    """Load site base URLs from config/sites.yaml."""
    from applypilot.config import load_base_urls
    return load_base_urls()


def resolve_url(raw_url: str, site: str) -> str | None:
    """Resolve a stored URL to an absolute URL."""
    if not raw_url:
        return None

    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        return raw_url

    if site == "WelcomeToTheJungle":
        return None

    if site == "Randstad Canada" and "/" not in raw_url:
        return f"https://www.randstad.ca/jobs/search/{raw_url}"

    if site == "4DayWeek" and raw_url in ("/", "/jobs"):
        return None

    base = _load_base_urls().get(site)
    if not base:
        return None

    if ";jsessionid=" in raw_url:
        raw_url = raw_url.split(";jsessionid=")[0]

    return urljoin(base, raw_url)


def resolve_all_urls(conn: sqlite3.Connection) -> dict:
    """Resolve all relative URLs in the database. Returns stats."""
    rows = conn.execute("SELECT url, site FROM jobs").fetchall()
    resolved = 0
    failed = 0
    already_absolute = 0

    for row in rows:
        url, site = row[0], row[1]
        if url.startswith("http://") or url.startswith("https://"):
            already_absolute += 1
            continue

        new_url = resolve_url(url, site)
        if new_url and new_url != url:
            try:
                conn.execute("UPDATE jobs SET url = ? WHERE url = ?", (new_url, url))
                resolved += 1
            except sqlite3.IntegrityError:
                conn.execute("DELETE FROM jobs WHERE url = ?", (url,))
                resolved += 1
        else:
            failed += 1

    # Also resolve relative application_urls
    app_resolved = 0
    rows = conn.execute(
        "SELECT url, site, application_url FROM jobs "
        "WHERE application_url IS NOT NULL AND application_url != '' "
        "AND application_url NOT LIKE 'http%'"
    ).fetchall()
    for row in rows:
        url, site, app_url = row[0], row[1], row[2]
        new_app = resolve_url(app_url, site)
        if (
            not new_app
            and isinstance(url, str)
            and url.startswith(("http://", "https://"))
        ):
            new_app = urljoin(url, app_url)
        if new_app and new_app != app_url:
            conn.execute("UPDATE jobs SET application_url = ? WHERE url = ?", (new_app, url))
            app_resolved += 1

    backfilled = backfill_application_urls_from_descriptions(conn)
    linkedin_backfilled = backfill_linkedin_company_website_apply_urls(conn, limit=200)
    conn.commit()
    return {
        "resolved": resolved,
        "failed": failed,
        "already_absolute": already_absolute,
        "app_resolved": app_resolved,
        "app_backfilled": backfilled,
        "linkedin_company_apply_backfilled": linkedin_backfilled,
    }


def backfill_application_urls_from_descriptions(conn: sqlite3.Connection) -> int:
    """Set application_url from ATS links embedded in full_description when missing."""
    from applypilot.apply.apply_url_extract import (
        coerce_application_url,
        extract_best_apply_url_from_text,
    )

    rows = conn.execute(
        "SELECT url, application_url, full_description FROM jobs "
        "WHERE full_description IS NOT NULL AND length(full_description) > 200"
    ).fetchall()
    updated = 0
    for url, application_url, full_description in rows:
        if coerce_application_url(application_url):
            continue
        extracted = extract_best_apply_url_from_text(full_description)
        if not extracted:
            continue
        conn.execute(
            "UPDATE jobs SET application_url = ? WHERE url = ?",
            (extracted, url),
        )
        updated += 1
    return updated


def backfill_linkedin_company_website_apply_urls(
    conn: sqlite3.Connection,
    *,
    limit: int = 200,
) -> int:
    """For LinkedIn jobs, store 'Apply to company website' URL when present.

    This enables the apply worker to apply on the external ATS instead of skipping
    as manual LinkedIn.
    """
    rows = conn.execute(
        """
        SELECT url, application_url, site
        FROM jobs
        WHERE LOWER(COALESCE(url, '')) LIKE '%linkedin.com/jobs/view%'
          AND (application_url IS NULL OR application_url = '' OR LOWER(application_url) LIKE '%linkedin.com%')
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    if not rows:
        return 0

    updated = 0
    t0 = time.time()
    max_seconds = 45.0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA)
        page = context.new_page()
        for url, _app, _site in rows:
            if (time.time() - t0) > max_seconds:
                break
            try:
                page.goto(str(url), timeout=15000, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=2500)
                except Exception:
                    pass
                company_apply = extract_linkedin_company_website_apply_url(page)
                if not company_apply:
                    continue
                conn.execute(
                    "UPDATE jobs SET application_url = ? WHERE url = ?",
                    (company_apply, url),
                )
                updated += 1
            except Exception:
                continue
        conn.commit()
        browser.close()
    return updated


def resolve_wttj_urls(conn: sqlite3.Connection) -> int:
    """Re-fetch WTTJ Algolia API to get proper detail URLs and fix slug-as-title.
    Returns count of URLs updated."""
    wttj_jobs = conn.execute(
        "SELECT url, title FROM jobs WHERE site = 'WelcomeToTheJungle'"
    ).fetchall()

    if not wttj_jobs:
        return 0

    algolia_data: dict = {}

    def capture_algolia(response):
        if "algolia.net" in response.url and "/queries" in response.url:
            try:
                algolia_data["response"] = json.loads(response.text())
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        page.on("response", capture_algolia)
        page.goto(
            "https://www.welcometothejungle.com/en/jobs?query=developer&refinementList%5Bremote%5D%5B%5D=fulltime",
            timeout=60000,
        )
        page.wait_for_load_state("networkidle")
        browser.close()

    if not algolia_data.get("response"):
        log.warning("WTTJ: No Algolia response captured")
        return 0

    results = algolia_data["response"].get("results", [])
    slug_map: dict = {}
    for rs in results:
        for hit in rs.get("hits", []):
            slug = hit.get("slug", "")
            org = hit.get("organization", {})
            org_slug = org.get("slug", "") if isinstance(org, dict) else ""
            name = hit.get("name", "")
            if slug and org_slug:
                detail_url = f"https://www.welcometothejungle.com/en/companies/{org_slug}/jobs/{slug}"
                slug_map[slug] = {"url": detail_url, "name": name}

    updated = 0
    for row in wttj_jobs:
        old_url, old_title = row[0], row[1]
        slug = old_url.split("_DFNS_")[0] if "_DFNS_" in old_url else old_url
        match = slug_map.get(slug) or slug_map.get(old_url)
        if match:
            try:
                conn.execute(
                    "UPDATE jobs SET url = ?, title = ? WHERE url = ?",
                    (match["url"], match["name"] or old_title, old_url),
                )
                updated += 1
            except sqlite3.IntegrityError:
                conn.execute("DELETE FROM jobs WHERE url = ?", (old_url,))
                updated += 1
        else:
            for s, data in slug_map.items():
                if s in old_url or old_url in s:
                    try:
                        conn.execute(
                            "UPDATE jobs SET url = ?, title = ? WHERE url = ?",
                            (data["url"], data["name"] or old_title, old_url),
                        )
                        updated += 1
                    except sqlite3.IntegrityError:
                        conn.execute("DELETE FROM jobs WHERE url = ?", (old_url,))
                        updated += 1
                    break

    conn.commit()
    return updated


# -- Detail page intelligence ------------------------------------------------

def collect_detail_intelligence(page) -> dict:
    """Collect signals from a detail page. Lighter than discovery -- no API interception."""
    intel: dict = {"json_ld": [], "page_title": "", "final_url": ""}

    intel["page_title"] = page.title()
    intel["final_url"] = page.url

    for el in page.query_selector_all('script[type="application/ld+json"]'):
        try:
            data = json.loads(el.inner_text())
            intel["json_ld"].append(data)
        except Exception:
            pass

    return intel


# -- Tier 1: JSON-LD extraction -----------------------------------------------

def extract_from_json_ld(intel: dict) -> dict | None:
    """Extract description and apply URL from JSON-LD JobPosting.
    Returns {"full_description": str, "application_url": str|None} or None."""

    def find_job_posting(data):
        if isinstance(data, dict):
            if data.get("@type") == "JobPosting":
                return data
            if "@graph" in data and isinstance(data["@graph"], list):
                for item in data["@graph"]:
                    result = find_job_posting(item)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = find_job_posting(item)
                if result:
                    return result
        return None

    for ld in intel.get("json_ld", []):
        posting = find_job_posting(ld)
        if not posting:
            continue

        desc = posting.get("description", "")
        if not desc:
            continue

        desc_clean = clean_description(desc)
        if len(desc_clean) < 50:
            continue

        apply_url = None
        if posting.get("directApply"):
            apply_url = posting.get("url")
        if not apply_url:
            contact = posting.get("applicationContact")
            if isinstance(contact, dict):
                apply_url = contact.get("url")
        if not apply_url:
            apply_url = posting.get("url")

        return {
            "full_description": desc_clean,
            "application_url": apply_url,
        }

    return None


# -- Tier 2: Deterministic pattern matching ----------------------------------

APPLY_SELECTORS = [
    'a[href*="apply"]',
    'a[data-testid*="apply"]',
    'a[class*="apply"]',
    'a[aria-label*="pply"]',
    'button[data-testid*="apply"]',
    'a#apply_button',
    '.postings-btn-wrapper a',
    'a.ashby-job-posting-apply-button',
    '#grnhse_app a[href*="apply"]',
    'a[data-qa="btn-apply"]',
    'a[class*="btn-apply"]',
    'a[class*="apply-btn"]',
    'a[class*="apply-button"]',
]

DESCRIPTION_SELECTORS = [
    '#job-description',
    '#job_description',
    '#jobDescriptionText',
    '.job-description',
    '.job_description',
    '[class*="job-description"]',
    '[class*="jobDescription"]',
    '[data-testid*="description"]',
    '[data-testid="job-description"]',
    '.posting-page .posting-categories + div',
    '#content .posting-page',
    '#app_body .content',
    '#grnhse_app .content',
    '.ashby-job-posting-description',
    '[class*="posting-description"]',
    '[class*="job-detail"]',
    '[class*="jobDetail"]',
    '[class*="job-content"]',
    '[class*="job-body"]',
    '[role="main"] article',
    'main article',
    'article[class*="job"]',
    '.job-posting-content',
]


def extract_apply_url_deterministic(page) -> str | None:
    """Try known CSS patterns for apply buttons/links."""
    company_apply = extract_linkedin_company_website_apply_url(page)
    if company_apply:
        return company_apply

    for sel in APPLY_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                href = el.get_attribute("href")
                if href and href != "#":
                    return href
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "button":
                    parent_href = el.evaluate("el => el.parentElement?.querySelector('a')?.href || null")
                    if parent_href:
                        return parent_href
                    return page.url
        except Exception:
            continue

    try:
        links = page.query_selector_all("a")
        for link in links:
            text = link.inner_text().strip().lower()
            if "apply" in text and len(text) < 50:
                href = link.get_attribute("href")
                if href and href != "#" and "javascript:" not in href:
                    return href
    except Exception:
        pass

    return None


def _decode_linkedin_redirect(url: str) -> str | None:
    """Decode LinkedIn redirect URLs to the underlying target when present."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if "linkedin.com" not in (parsed.netloc or ""):
        return None
    qs = parse_qs(parsed.query or "")
    raw = None
    for key in ("url", "redirect", "target"):
        if key in qs and qs[key]:
            raw = qs[key][0]
            break
    if not raw:
        return None
    decoded = unquote(raw).strip()
    if decoded.startswith("http://") or decoded.startswith("https://"):
        return decoded
    return None


def extract_linkedin_company_website_apply_url(page) -> str | None:
    """Prefer 'Apply to company website' over LinkedIn Easy Apply when present."""
    try:
        current = str(page.url or "")
    except Exception:
        current = ""
    if "linkedin.com/jobs" not in current and "linkedin.com" not in current:
        return None

    # LinkedIn usually renders one or two primary apply buttons; prefer any that mention company website.
    candidates = []
    for sel in [
        "a[href]",
        "button",
    ]:
        try:
            for el in page.query_selector_all(sel):
                text = (el.inner_text() or "").strip().lower()
                if not text:
                    continue
                if "apply" not in text:
                    continue
                if "company website" not in text and "company site" not in text:
                    continue
                href = el.get_attribute("href")
                if not href and sel == "button":
                    href = el.evaluate("el => el.closest('a')?.href || el.parentElement?.querySelector('a')?.href || null")
                if href:
                    candidates.append(href)
        except Exception:
            continue

    for href in candidates:
        if href.startswith(("http://", "https://")):
            decoded = _decode_linkedin_redirect(href)
            return decoded or href
    return None


def extract_description_deterministic(page) -> str | None:
    """Try known CSS patterns for the job description block."""
    for sel in DESCRIPTION_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) >= 100:
                    return clean_description(text)
        except Exception:
            continue

    return None


# -- Tier 3: LLM extraction -------------------------------------------------

DETAIL_EXTRACT_PROMPT = """You are extracting job details from a single job posting page.

PAGE URL: {url}
PAGE TITLE: {title}

Find TWO things in the HTML below:
1. The full job description text (responsibilities, requirements, etc.)
2. The URL of the "Apply" button/link

Rules:
- For description: extract the FULL text. Include all sections (About, Responsibilities, Requirements, etc.)
- For apply URL: find the href of the link/button that starts the application process
- If you cannot find one, set it to null

Return ONLY valid JSON:
{{"full_description": "the complete job description text here", "application_url": "https://..." or null}}

No explanation, no markdown. Keep reasoning under 20 words.

HTML:
{content}"""


def extract_main_content(page) -> str:
    """Extract the main content area, stripped of navigation noise."""
    for sel in ["main", "article", '[role="main"]', "#content", ".content"]:
        try:
            el = page.query_selector(sel)
            if el:
                text_len = len(el.inner_text().strip())
                if text_len > 200:
                    html = el.inner_html()
                    if len(html) < 50000:
                        return clean_content_html(html)
        except Exception:
            continue

    try:
        html = page.evaluate("""
            () => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('nav, header, footer, script, style, noscript, svg, iframe').forEach(el => el.remove());
                return clone.innerHTML;
            }
        """)
        return clean_content_html(html[:50000])
    except Exception:
        return ""


def clean_content_html(html: str) -> str:
    """Clean detail page HTML for LLM consumption."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.select("script, style, noscript, svg, iframe, nav, header, footer"):
        tag.decompose()

    for tag in soup.find_all(True):
        new_attrs: dict = {}
        for attr, val in list(tag.attrs.items()):
            if attr in ("id", "href", "class", "role", "aria-label", "data-testid", "name", "for", "type"):
                if attr == "class":
                    classes = val if isinstance(val, list) else val.split()
                    kept = [c for c in classes if len(c) < 30 and not re.match(r"^[a-z]{1,2}-\d+$", c)]
                    if kept:
                        new_attrs["class"] = " ".join(kept[:3])
                else:
                    new_attrs[attr] = val
            elif attr.startswith("data-") or attr.startswith("aria-"):
                new_attrs[attr] = val
        tag.attrs = new_attrs

    return str(soup)


def extract_with_llm(page, url: str) -> dict:
    """Send focused HTML to LLM for extraction. Fallback tier."""
    content = extract_main_content(page)
    if not content:
        return {"full_description": None, "application_url": None}

    title = ""
    try:
        title = page.title()
    except Exception:
        pass

    prompt = DETAIL_EXTRACT_PROMPT.format(
        url=url,
        title=title,
        content=content[:30000],
    )

    try:
        client = get_client()
        t0 = time.time()
        raw = client.ask(
            prompt,
            temperature=0.0,
            max_tokens=4096,
            operation="enrich_detail",
        )
        elapsed = time.time() - t0
        log.info("LLM: %d chars in, %.1fs", len(prompt), elapsed)

        from applypilot.discovery.smartextract import extract_json
        result = extract_json(raw)
        desc = result.get("full_description")
        apply_url = result.get("application_url")

        if desc:
            desc = clean_description(desc)

        return {"full_description": desc, "application_url": apply_url}
    except Exception as e:
        log.error("LLM ERROR: %s", e)
        return {"full_description": None, "application_url": None}


# -- Description cleaning ---------------------------------------------------

def clean_description(text: str) -> str:
    """Convert HTML description to clean readable text."""
    if not text:
        return ""

    if "<" in text and ">" in text:
        soup = BeautifulSoup(text, "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "li", "tr"]):
            tag.insert_before("\n")
            tag.insert_after("\n")
        for li in soup.find_all("li"):
            li.insert_before("- ")
        text = soup.get_text()

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# -- Orchestration -----------------------------------------------------------

SITE_DELAYS = {
    "RemoteOK": 3.0,
    "WelcomeToTheJungle": 2.0,
    "Job Bank Canada": 1.5,
    "CareerJet Canada": 3.0,
    "Hacker News Jobs": 1.0,
    "BuiltIn Remote": 2.0,
}

RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
PERMANENT_FAILURES = {404, 410, 451}


def _scrape_detail_page_once(page, url: str) -> dict:
    """Single navigation + extraction cascade for one detail page."""
    result: dict = {
        "full_description": None,
        "application_url": None,
        "status": "error",
        "tier_used": None,
        "error": None,
    }
    t0 = time.time()

    try:
        resp = page.goto(url, timeout=45000)
        if resp and resp.status in PERMANENT_FAILURES:
            result["error"] = f"HTTP {resp.status}"
            result["elapsed"] = time.time() - t0
            return result
        if resp and resp.status in RETRYABLE_STATUSES:
            result["error"] = f"HTTP {resp.status}"
            result["elapsed"] = time.time() - t0
            return result
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
    except Exception as e:
        err_str = str(e)
        if "timeout" in err_str.lower():
            result["error"] = "timeout"
        else:
            result["error"] = err_str[:200]
        result["elapsed"] = time.time() - t0
        return result

    intel = collect_detail_intelligence(page)

    # Tier 1: JSON-LD
    json_ld_result = extract_from_json_ld(intel)
    if json_ld_result and json_ld_result.get("full_description"):
        result.update(json_ld_result)
        result["tier_used"] = 1
        if not result.get("application_url"):
            apply = extract_apply_url_deterministic(page)
            if apply:
                result["application_url"] = apply
        result["status"] = "ok" if result.get("application_url") else "partial"
        result["elapsed"] = time.time() - t0
        return result

    # Tier 2: Deterministic CSS
    desc = extract_description_deterministic(page)
    apply = extract_apply_url_deterministic(page)

    if desc:
        result["full_description"] = desc
        result["application_url"] = apply
        result["tier_used"] = 2
        result["status"] = "ok" if apply else "partial"
        result["elapsed"] = time.time() - t0
        return result

    tier2_apply = apply

    # Tier 3: LLM
    llm_result = extract_with_llm(page, url)
    result["full_description"] = llm_result.get("full_description")
    result["application_url"] = llm_result.get("application_url") or tier2_apply
    result["tier_used"] = 3

    if result.get("full_description"):
        result["status"] = "ok" if result.get("application_url") else "partial"
    elif result.get("application_url"):
        result["status"] = "partial"
    else:
        result["status"] = "error"
        result["error"] = "no data extracted"

    result["elapsed"] = time.time() - t0
    return result


def scrape_detail_page(page, url: str) -> dict:
    """Full cascade for one detail page with in-run retries on transient failures."""
    from applypilot.enrichment.pending import is_retryable_detail_error

    last: dict | None = None
    for attempt in range(DETAIL_GOTO_ATTEMPTS):
        result = _scrape_detail_page_once(page, url)
        if result["status"] in ("ok", "partial"):
            return result
        err = result.get("error")
        if not is_retryable_detail_error(err) or attempt >= DETAIL_GOTO_ATTEMPTS - 1:
            return result
        log.warning(
            "Detail scrape retry %d/%d for %s: %s",
            attempt + 1,
            DETAIL_GOTO_ATTEMPTS,
            url[:80],
            err,
        )
        time.sleep(min(2.0 * (attempt + 1), 8.0))
        last = result
    return last or result


def scrape_site_batch(
    conn: sqlite3.Connection | None,
    site: str,
    jobs: list[tuple],
    delay: float = 2.0,
    max_jobs: int | None = None,
) -> dict:
    """Process all jobs for one site using shared browser context.

    If conn is None, creates its own DB connection.
    """
    stats: dict = {"processed": 0, "ok": 0, "partial": 0, "error": 0, "tiers": {1: 0, 2: 0, 3: 0}}

    if max_jobs:
        jobs = jobs[:max_jobs]

    if not jobs:
        return stats

    own_conn = conn is None
    if own_conn:
        conn = init_db()

    now = datetime.now(timezone.utc).isoformat()

    try:
        with sync_playwright() as p:
            launch_opts: dict = {"headless": True}
            if _PROXY_CONFIG:
                launch_opts["proxy"] = _PROXY_CONFIG["playwright"]
            browser = p.chromium.launch(**launch_opts)
            context = browser.new_context(user_agent=UA)
            page = context.new_page()

            for i, (url, title) in enumerate(jobs):
                log.info("[%d/%d] %s", i + 1, len(jobs), title[:50] if title else url[:50])

                result = scrape_detail_page(page, url)
                stats["processed"] += 1

                tier = result.get("tier_used")
                status = result["status"]
                elapsed = result.get("elapsed", 0)

                if tier:
                    stats["tiers"][tier] = stats["tiers"].get(tier, 0) + 1

                tier_str = f"T{tier}" if tier else "--"
                desc_len = len(result.get("full_description") or "")
                apply_str = "yes" if result.get("application_url") else "no"
                err_str = f" | err={result.get('error')}" if result.get("error") else ""

                log.info("  %s | %s | desc=%s chars | apply=%s | %.1fs%s",
                         status, tier_str, f"{desc_len:,}", apply_str, elapsed, err_str)

                if status in ("ok", "partial"):
                    stats[status] += 1
                else:
                    stats["error"] += 1
                persist_detail_scrape_result(conn, url, result, now=now)
                conn.commit()

                if i < len(jobs) - 1:
                    time.sleep(delay)

            browser.close()
    finally:
        if own_conn:
            conn.close()

    return stats


def _run_detail_scraper(
    conn: sqlite3.Connection,
    sites: list[str] | None = None,
    max_per_site: int | None = None,
    workers: int = 1,
) -> dict:
    """Groups pending jobs by site and processes each batch.

    Sequential by default. When workers > 1, processes multiple site batches
    in parallel using ThreadPoolExecutor (each thread gets its own browser
    and DB connection).

    Returns aggregate stats dict.
    """
    skip_filter = " AND ".join(f"site != '{s}'" for s in SKIP_DETAIL_SITES)
    where = f"WHERE {detail_pending_clause()} AND {skip_filter}"
    rows = conn.execute(
        f"SELECT url, title, site FROM jobs {where} ORDER BY site"
    ).fetchall()

    if not rows:
        log.info("No pending jobs to scrape.")
        return {
            "processed": 0,
            "ok": 0,
            "partial": 0,
            "error": 0,
        }

    site_jobs: dict[str, list[tuple]] = {}
    for row in rows:
        url, title, site = row[0], row[1], row[2]
        if sites and site not in sites:
            continue
        site_jobs.setdefault(site, []).append((url, title))

    log.info("Pending: %d jobs across %d sites (workers=%d)", len(rows), len(site_jobs), workers)
    for site, jobs in site_jobs.items():
        log.info("  %s: %d jobs", site, len(jobs))

    known_order = [
        "RemoteOK", "Job Bank Canada", "BuiltIn Remote",
        "WelcomeToTheJungle", "CareerJet Canada", "Hacker News Jobs",
    ]
    order = [s for s in known_order if s in site_jobs]
    order += [s for s in sorted(site_jobs.keys()) if s not in order]

    total_stats: dict = {
        "processed": 0,
        "ok": 0,
        "partial": 0,
        "error": 0,
        "tiers": {1: 0, 2: 0, 3: 0},
    }

    def _merge_stats(stats: dict) -> None:
        for k in ("processed", "ok", "partial", "error"):
            total_stats[k] += stats[k]
        for t, count in stats["tiers"].items():
            total_stats["tiers"][t] = total_stats["tiers"].get(t, 0) + count

    if workers > 1 and len(order) > 1:
        # Parallel mode: each site batch runs in its own thread with its own
        # DB connection (conn=None tells scrape_site_batch to create one)
        def _scrape_site(site: str) -> dict:
            jobs = site_jobs[site]
            delay = SITE_DELAYS.get(site, 2.0)
            log.info("%s -- %d jobs (delay=%.1fs)", site, len(jobs), delay)
            stats = scrape_site_batch(None, site, jobs, delay=delay, max_jobs=max_per_site)
            log.info("%s summary: %d ok, %d partial, %d error | T1=%d T2=%d T3=%d",
                     site, stats["ok"], stats["partial"], stats["error"],
                     stats["tiers"].get(1, 0), stats["tiers"].get(2, 0), stats["tiers"].get(3, 0))
            return stats

        with ThreadPoolExecutor(max_workers=min(workers, len(order))) as pool:
            futures = {pool.submit(_scrape_site, site): site for site in order}
            for future in as_completed(futures):
                _merge_stats(future.result())
    else:
        # Sequential mode (default)
        for site in order:
            jobs = site_jobs[site]
            delay = SITE_DELAYS.get(site, 2.0)
            log.info("%s -- %d jobs (delay=%.1fs)", site, len(jobs), delay)

            stats = scrape_site_batch(conn, site, jobs, delay=delay, max_jobs=max_per_site)
            _merge_stats(stats)

            log.info("Site summary: %d ok, %d partial, %d error | T1=%d T2=%d T3=%d",
                     stats["ok"], stats["partial"], stats["error"],
                     stats["tiers"].get(1, 0), stats["tiers"].get(2, 0), stats["tiers"].get(3, 0))

    log.info("TOTAL: %d processed | %d ok | %d partial | %d error",
             total_stats["processed"], total_stats["ok"], total_stats["partial"], total_stats["error"])
    log.info("Tier distribution: T1=%d T2=%d T3=%d",
             total_stats["tiers"].get(1, 0), total_stats["tiers"].get(2, 0), total_stats["tiers"].get(3, 0))

    llm_calls = total_stats["tiers"].get(3, 0)
    total = total_stats["processed"]
    if total > 0:
        savings = ((total - llm_calls) / total) * 100
        log.info("LLM calls: %d/%d (%.0f%% saved)", llm_calls, total, savings)

    return total_stats


# -- Streaming detail scraper (for sequential pipeline) ----------------------

def stream_detail(
    upstream_done,
    my_done,
    proxy_str: str | None = None,
    poll_interval: float = 5.0,
) -> None:
    """Streaming detail scraper: polls DB for un-scraped jobs, scrapes sites sequentially.

    Args:
        upstream_done: Event set when discover+extract done. None = run once.
        my_done: Event to set when this stage completes.
        proxy_str: Proxy in host:port:user:pass format.
        poll_interval: Seconds to sleep when no pending jobs found.
    """
    if proxy_str:
        set_proxy(proxy_str)

    conn = init_db()

    url_stats = resolve_all_urls(conn)
    log.info("URL resolution: %d resolved, %d absolute",
             url_stats['resolved'], url_stats['already_absolute'])

    total_ok = 0
    total_err = 0
    t0 = time.time()

    try:
        while True:
            skip_filter = " AND ".join(f"site != '{s}'" for s in SKIP_DETAIL_SITES)
            rows = conn.execute(
                "SELECT url, title, site FROM jobs "
                f"WHERE {detail_pending_clause()} AND {skip_filter} "
                "ORDER BY site LIMIT 200"
            ).fetchall()

            if rows:
                site_jobs: dict[str, list[tuple]] = {}
                for row in rows:
                    url, title, site = row[0], row[1], row[2]
                    site_jobs.setdefault(site, []).append((url, title))

                for site, jobs in site_jobs.items():
                    delay = SITE_DELAYS.get(site, 2.0)
                    log.info("%s: %d jobs (delay=%.1fs)", site, len(jobs), delay)

                    try:
                        stats = scrape_site_batch(conn, site, jobs, delay=delay)
                        total_ok += stats["ok"] + stats["partial"]
                        total_err += stats["error"]
                        log.info("%s: %d ok, %d partial, %d error",
                                 site, stats['ok'], stats['partial'], stats['error'])
                    except Exception as e:
                        log.error("%s: CRASHED: %s", site, e)

            upstream_finished = upstream_done is None or upstream_done.is_set()
            if upstream_finished and not rows:
                break
            if not rows:
                time.sleep(poll_interval)
    finally:
        elapsed = time.time() - t0
        if total_ok or total_err:
            log.info("DONE: %d ok, %d errors in %.1fs", total_ok, total_err, elapsed)
        conn.close()
        my_done.set()


# -- Public entry point ------------------------------------------------------

def run_enrichment(limit: int = 100, workers: int = 1) -> dict:
    """Main entry point for detail page enrichment.

    Fetches pending jobs from the database (those without full_description),
    resolves relative URLs, then runs the three-tier extraction cascade on
    each detail page.

    Args:
        limit: Maximum number of jobs per site to process.
        workers: Number of parallel threads for site batch processing. Default 1 (sequential).

    Returns:
        Dict with stats: processed, ok, partial, error, tiers.
    """
    conn = init_db()

    # URL resolution first
    url_stats = resolve_all_urls(conn)
    log.info("URL resolution: %d resolved, %d absolute, %d failed",
             url_stats["resolved"], url_stats["already_absolute"], url_stats["failed"])

    # WTTJ special handling
    wttj_count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE site = 'WelcomeToTheJungle'"
    ).fetchone()[0]
    if wttj_count > 0:
        sample = conn.execute(
            "SELECT url FROM jobs WHERE site = 'WelcomeToTheJungle' LIMIT 1"
        ).fetchone()
        if sample and not sample[0].startswith("http"):
            updated = resolve_wttj_urls(conn)
            log.info("WTTJ: %d URLs updated", updated)

    # Run the detail scraper
    stats = _run_detail_scraper(conn, max_per_site=limit, workers=workers)

    return stats
