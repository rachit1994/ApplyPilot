"""Prompt for AI browser discover (no application submit)."""

DISCOVER_AGENT_PROMPT = """You are discovering job listings on a careers site using the browser.

GOAL: Collect job postings matching senior engineering / AI / leadership roles.
Return a final line exactly: JOBS_JSON: [{{"url":"...","title":"...","location":"...","salary":null,"description":"..."}}]

RULES:
- Use the browser to search, filter (location/remote/senior), paginate, or load more as needed.
- Do NOT submit job applications or upload resumes.
- Do NOT log in unless the page is unusable without it — if login required, stop and say BLOCKED: login required.
- If CAPTCHA or hard block, say BLOCKED: captcha.
- Prefer direct job posting URLs.
- Stop after {max_pages} pages or when no new listings appear.
- Fill search/filter fields only (not application forms).

Start URL: {start_url}
Site name: {site_name}
Search hints: {search_terms}
Location hints: {location}
"""
