"""
Lightweight scraper for company About and Careers pages.

Design choices:
- We do NOT try to scrape LinkedIn (ToS + needs auth). User pastes manually.
- We DO try About + Careers pages because they sit on the company's own
  domain, are usually static HTML, and contain high-signal content:
  * About page reveals positioning and strategic narrative
  * Careers page reveals what teams they are growing → reverse-engineer pain
- We use a strict timeout and User-Agent so we don't hang the Streamlit UI.
- If scraping fails, we return a graceful empty payload — the pipeline still
  proceeds with whatever else the user provided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 8  # seconds
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Candidate paths to probe for About / Careers content. Ordered by likelihood.
ABOUT_CANDIDATES = ["/about", "/about-us", "/company", "/who-we-are", "/our-story"]
CAREERS_CANDIDATES = ["/careers", "/jobs", "/join-us", "/work-with-us", "/team"]


@dataclass
class ScrapedPage:
    url: str
    page_type: str  # "homepage" | "about" | "careers"
    text: str       # cleaned visible text, truncated


@dataclass
class ScrapeResult:
    pages: List[ScrapedPage]
    errors: List[str]


def _clean_html_text(html: str, max_chars: int = 8000) -> str:
    """Strip HTML noise and return readable text, truncated."""
    soup = BeautifulSoup(html, "html.parser")
    # Drop common non-content tags
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse repeated whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    return text[:max_chars]


def _try_fetch(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            return resp.text
    except requests.RequestException:
        return None
    return None


def _normalise_base(url: str) -> str:
    """Ensure URL has scheme and trailing slash for urljoin."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def scrape_company_site(company_url: str) -> ScrapeResult:
    """Probe homepage + About + Careers candidates for a given company URL.

    Returns up to 3 pages of cleaned text. Errors are non-fatal — collected
    for transparency but do not raise.
    """
    pages: List[ScrapedPage] = []
    errors: List[str] = []

    try:
        base = _normalise_base(company_url)
    except Exception as exc:  # malformed URL
        return ScrapeResult(pages=[], errors=[f"Invalid company URL: {exc}"])

    # 1. Homepage
    home_html = _try_fetch(base)
    if home_html:
        pages.append(ScrapedPage(url=base, page_type="homepage", text=_clean_html_text(home_html)))
    else:
        errors.append(f"Could not fetch homepage at {base}")

    # 2. About page — probe candidates
    about_page = _probe_paths(base, ABOUT_CANDIDATES, page_type="about")
    if about_page:
        pages.append(about_page)
    else:
        errors.append("No About page found at common paths.")

    # 3. Careers page
    careers_page = _probe_paths(base, CAREERS_CANDIDATES, page_type="careers")
    if careers_page:
        pages.append(careers_page)
    else:
        errors.append("No Careers page found at common paths.")

    return ScrapeResult(pages=pages, errors=errors)


def _probe_paths(base: str, candidates: List[str], page_type: str) -> Optional[ScrapedPage]:
    for path in candidates:
        full = urljoin(base, path.lstrip("/"))
        html = _try_fetch(full)
        if html:
            return ScrapedPage(url=full, page_type=page_type, text=_clean_html_text(html))
    return None


def format_scrape_for_prompt(result: ScrapeResult) -> str:
    """Render the scrape result as a prompt-friendly markdown block."""
    if not result.pages:
        return "[No company website content available]"
    blocks = []
    for page in result.pages:
        blocks.append(f"### {page.page_type.upper()} — {page.url}\n\n{page.text}\n")
    return "\n---\n".join(blocks)