"""Text-to-PDF conversion for tailored resumes and cover letters.

Parses the structured text resume format, renders via an HTML/CSS template,
and exports to PDF using headless Chromium via Playwright.
"""

import html
import logging
import re
from pathlib import Path

from applypilot.config import TAILORED_DIR

log = logging.getLogger(__name__)

RESUME_SECTION_HEADERS = frozenset(
    {
        "SUMMARY",
        "TECHNICAL SKILLS",
        "SKILLS",
        "CORE COMPETENCIES",
        "EXPERIENCE",
        "WORK EXPERIENCE",
        "PROFESSIONAL EXPERIENCE",
        "PROJECTS",
        "SELECTED PROJECTS",
        "EDUCATION",
        "CERTIFICATIONS",
        "AWARDS",
        "PUBLICATIONS",
        "LEADERSHIP",
        "VOLUNTEER EXPERIENCE",
        "LANGUAGES",
    }
)


def _is_section_header(line: str) -> bool:
    """True for known resume section titles, not employer names like MIRA."""
    stripped = line.strip()
    return bool(stripped) and stripped.upper() in RESUME_SECTION_HEADERS


def _split_contact_line(line: str) -> tuple[str, list[str]]:
    """Split 'City · phone · email · links' into location and contact parts."""
    parts = [p.strip() for p in re.split(r"\s*[·|]\s*", line) if p.strip()]
    if not parts:
        return "", []

    location = ""
    contact_parts: list[str] = []
    for idx, part in enumerate(parts):
        looks_like_location = (
            idx == 0
            and "@" not in part
            and not part.lower().startswith(("http://", "https://"))
            and not re.search(r"\d{5,}", part.replace(" ", "").replace("-", ""))
            and ("," in part or re.search(r"\b(india|usa|uk|remote)\b", part, re.I))
        )
        if looks_like_location:
            location = part
        else:
            contact_parts.append(part)
    if not contact_parts and parts:
        contact_parts = parts if not location else contact_parts
    return location, contact_parts


def _format_contact_part(part: str) -> str:
    """Render one contact token with mailto/links when appropriate."""
    safe = html.escape(part.strip())
    if "@" in part and " " not in part.split("@", 1)[0]:
        return f'<a href="mailto:{html.escape(part.strip())}">{safe}</a>'
    if part.strip().lower().startswith(("http://", "https://")):
        display = re.sub(r"^https?://(www\.)?", "", part.strip(), flags=re.I)
        return f'<a href="{html.escape(part.strip())}">{html.escape(display)}</a>'
    return safe


# ── Resume Parser ────────────────────────────────────────────────────────

def parse_resume(text: str) -> dict:
    """Parse a structured text resume into sections.

    Expects a format with header lines (name, title, location, contact)
    followed by ALL-CAPS section headers (SUMMARY, TECHNICAL SKILLS, etc.).

    Args:
        text: Full resume text.

    Returns:
        {"name": str, "title": str, "location": str, "contact": str, "sections": dict}
    """
    lines = [line.rstrip() for line in text.strip().split("\n")]

    # Header: first few lines before SUMMARY
    header_lines: list[str] = []
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().upper() == "SUMMARY":
            body_start = i
            break
        if line.strip():
            header_lines.append(line.strip())

    name = header_lines[0] if len(header_lines) > 0 else ""
    title = header_lines[1] if len(header_lines) > 1 else ""
    location = ""
    contact_parts: list[str] = []
    if len(header_lines) > 3:
        location = header_lines[2]
        contact_parts = [header_lines[3]]
    elif len(header_lines) > 2:
        location, contact_parts = _split_contact_line(header_lines[2])
        if not contact_parts and header_lines[2]:
            contact_parts = [header_lines[2]]

    # Split body into sections by known ALL-CAPS headers
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines[body_start:]:
        stripped = line.strip()
        if _is_section_header(stripped):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "name": name,
        "title": title,
        "location": location,
        "contact": contact_parts,
        "sections": sections,
    }


def parse_skills(text: str) -> list[tuple[str, str]]:
    """Parse skills section into (category, value) pairs.

    Args:
        text: The TECHNICAL SKILLS section text.

    Returns:
        List of (category_name, skills_string) tuples.
    """
    skills: list[tuple[str, str]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            cat, val = line.split(":", 1)
            skills.append((cat.strip(), val.strip()))
    return skills


def parse_entries(text: str) -> list[dict]:
    """Parse experience/project entries from section text.

    Args:
        text: The EXPERIENCE or PROJECTS section text.

    Returns:
        List of {"title": str, "subtitle": str, "bullets": list[str]} dicts.
    """
    entries: list[dict] = []
    lines = text.strip().split("\n")
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") or stripped.startswith("\u2022 "):
            if current:
                current["bullets"].append(stripped[2:].strip())
        elif current is None or (
            not stripped.startswith("-")
            and not stripped.startswith("\u2022")
            and len(current.get("bullets", [])) > 0
        ):
            # New entry
            if current:
                entries.append(current)
            current = {"title": stripped, "subtitle": "", "bullets": []}
        elif current and not current["subtitle"]:
            current["subtitle"] = stripped
        else:
            if current:
                current["bullets"].append(stripped)

    if current:
        entries.append(current)

    return entries


# ── HTML Template ────────────────────────────────────────────────────────

def build_html(resume: dict) -> str:
    """Build professional resume HTML from parsed data.

    Args:
        resume: Parsed resume dict from parse_resume().

    Returns:
        Complete HTML string ready for PDF rendering.
    """
    sections = resume["sections"]

    # Skills
    skills_html = ""
    if "TECHNICAL SKILLS" in sections:
        skills = parse_skills(sections["TECHNICAL SKILLS"])
        rows = ""
        for cat, val in skills:
            rows += f'<div class="skill-row"><span class="skill-cat">{cat}:</span> {val}</div>\n'
        skills_html = f'<div class="section"><div class="section-title">Technical Skills</div>{rows}</div>'

    # Experience
    exp_html = ""
    if "EXPERIENCE" in sections:
        entries = parse_entries(sections["EXPERIENCE"])
        items = ""
        for e in entries:
            bullets = "".join(f"<li>{b}</li>" for b in e["bullets"])
            subtitle = f'<div class="entry-subtitle">{e["subtitle"]}</div>' if e["subtitle"] else ""
            items += f'<div class="entry"><div class="entry-title">{e["title"]}</div>{subtitle}<ul>{bullets}</ul></div>'
        exp_html = f'<div class="section"><div class="section-title">Experience</div>{items}</div>'

    # Projects
    proj_html = ""
    if "PROJECTS" in sections:
        entries = parse_entries(sections["PROJECTS"])
        items = ""
        for e in entries:
            bullets = "".join(f"<li>{b}</li>" for b in e["bullets"])
            subtitle = f'<div class="entry-subtitle">{e["subtitle"]}</div>' if e["subtitle"] else ""
            items += f'<div class="entry"><div class="entry-title">{e["title"]}</div>{subtitle}<ul>{bullets}</ul></div>'
        proj_html = f'<div class="section"><div class="section-title">Projects</div>{items}</div>'

    # Education
    edu_html = ""
    if "EDUCATION" in sections:
        edu_text = sections["EDUCATION"].strip()
        edu_html = f'<div class="section"><div class="section-title">Education</div><div class="edu">{edu_text}</div></div>'

    # Summary
    summary_html = ""
    if "SUMMARY" in sections:
        summary_html = f'<div class="section"><div class="section-title">Summary</div><div class="summary">{sections["SUMMARY"].strip()}</div></div>'

    contact_parts = resume.get("contact") or []
    if isinstance(contact_parts, str):
        contact_parts = [p.strip() for p in re.split(r"\s*[·|]\s*", contact_parts) if p.strip()]
    contact_html = " &nbsp;·&nbsp; ".join(_format_contact_part(p) for p in contact_parts)

    location = html.escape(resume["location"])
    location_html = f'<div class="location">{location}</div>' if location else ""

    name = html.escape(resume["name"])
    title = html.escape(resume["title"])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.45in 0.55in;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
body {{
    font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.35;
    color: #1a1a1a;
}}
.header {{
    text-align: center;
    margin-bottom: 6px;
    padding-bottom: 6px;
    border-bottom: 2px solid #1a3a5c;
}}
.name {{
    font-size: 20pt;
    font-weight: 700;
    color: #1a3a5c;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
.title {{
    font-size: 11pt;
    font-weight: 600;
    color: #2a5a7a;
    margin: 2px 0 3px;
}}
.location {{
    font-size: 9pt;
    color: #444;
    margin-bottom: 2px;
}}
.contact {{
    font-size: 8.5pt;
    color: #333;
    line-height: 1.45;
}}
.contact a {{
    color: #2c3e50;
    text-decoration: none;
}}
.section {{
    margin-top: 5px;
}}
.section-title {{
    font-size: 10pt;
    font-weight: 700;
    color: #1a3a5c;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    border-bottom: 1.5px solid #2a7ab5;
    padding-bottom: 1px;
    margin-bottom: 3px;
}}
.summary {{
    font-size: 9.5pt;
    color: #333;
    line-height: 1.4;
}}
.skill-row {{
    font-size: 9.5pt;
    margin: 0;
    line-height: 1.35;
}}
.skill-cat {{
    font-weight: 600;
    color: #1a3a5c;
}}
.entry {{
    margin-bottom: 4px;
    break-inside: avoid;
}}
.entry-title {{
    font-weight: 600;
    font-size: 10pt;
    color: #1a3a5c;
}}
.entry-subtitle {{
    font-size: 9pt;
    color: #4a7a9b;
    font-style: italic;
    margin-bottom: 1px;
}}
ul {{
    margin-left: 14px;
    padding: 0;
}}
li {{
    font-size: 9.5pt;
    margin-bottom: 1px;
    line-height: 1.35;
}}
.edu {{
    font-size: 10pt;
}}
</style>
</head>
<body>
<div class="header">
    <div class="name">{name}</div>
    <div class="title">{title}</div>
    {location_html}
    <div class="contact">{contact_html}</div>
</div>
{summary_html}
{skills_html}
{exp_html}
{proj_html}
{edu_html}
</body>
</html>"""


# ── PDF Renderer ─────────────────────────────────────────────────────────

def render_pdf(html: str, output_path: str) -> None:
    """Render HTML to PDF using Playwright's headless Chromium.

    Args:
        html: Complete HTML string.
        output_path: Path to write the PDF file.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=output_path,
            format="Letter",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        browser.close()


# ── Public API ───────────────────────────────────────────────────────────

def convert_to_pdf(
    text_path: Path, output_path: Path | None = None, html_only: bool = False
) -> Path:
    """Convert a text resume/cover letter to PDF.

    Args:
        text_path: Path to the .txt file to convert.
        output_path: Optional override for the output path. Defaults to same
            name with .pdf extension.
        html_only: If True, output HTML instead of PDF.

    Returns:
        Path to the generated PDF (or HTML) file.
    """
    text_path = Path(text_path)
    text = text_path.read_text(encoding="utf-8")
    resume = parse_resume(text)
    html = build_html(resume)

    if html_only:
        out = output_path or text_path.with_suffix(".html")
        out = Path(out)
        out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", out)
        return out

    out = output_path or text_path.with_suffix(".pdf")
    out = Path(out)
    render_pdf(html, str(out))
    log.info("PDF generated: %s", out)
    return out


def _txt_files_needing_pdf(limit: int | None = None) -> list[Path]:
    """Return tailored .txt files that do not yet have a sibling .pdf."""
    if not TAILORED_DIR.exists():
        return []

    need_pdf: list[Path] = []
    for path in sorted(TAILORED_DIR.glob("*.txt")):
        if path.name.endswith("_JOB.txt"):
            continue
        if path.with_suffix(".pdf").exists():
            continue
        need_pdf.append(path)
        if limit is not None and len(need_pdf) >= limit:
            break
    return need_pdf


def pending_pdf_conversions() -> int:
    """Count tailored .txt files missing a sibling PDF (filesystem truth)."""
    return len(_txt_files_needing_pdf())


def batch_convert(limit: int = 50) -> int:
    """Convert .txt files in TAILORED_DIR that don't have corresponding PDFs.

    Scans for .txt files (excluding _JOB.txt), checks if a .pdf with the same
    stem already exists, and converts any that are missing.

    Args:
        limit: Maximum number of files to convert.

    Returns:
        Number of PDFs generated.
    """
    if not TAILORED_DIR.exists():
        log.warning("Tailored directory does not exist: %s", TAILORED_DIR)
        return 0

    to_convert = _txt_files_needing_pdf(limit=limit)
    if not to_convert:
        log.debug("All text files already have PDFs.")
        return 0

    log.info("Converting %d files to PDF...", len(to_convert))
    converted = 0
    for f in to_convert:
        try:
            convert_to_pdf(f)
            converted += 1
        except Exception as e:
            log.error("Failed to convert %s: %s", f.name, e)

    log.info("Done: %d/%d PDFs generated in %s", converted, len(to_convert), TAILORED_DIR)
    return converted
