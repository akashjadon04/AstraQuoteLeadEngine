# ============================================================
# global_deep_crawler.py — Deep Website Scraper for Global Lead Engine
# Crawls website subpages (/about, /team, /contact) for Executive Contact & Email Extraction
# ============================================================

import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Regex patterns for executive names & titles
EXECUTIVE_TITLE_RE = re.compile(
    r"\b(owner|founder|co-founder|managing director|president|ceo|principal|director|general manager|partner)\b",
    re.IGNORECASE
)

NAME_AFTER_TITLE_RE = re.compile(
    r"\b(?:owner|founder|co-founder|managing director|president|ceo|principal|director|general manager|partner)\s*[:\-–—]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b",
    re.IGNORECASE
)

NAME_BEFORE_TITLE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*,\s*(?:owner|founder|co-founder|managing director|president|ceo|principal|director|general manager|partner)\b",
    re.IGNORECASE
)


def deep_crawl_company_website(website_url: str) -> Dict[str, Any]:
    """
    Deeply crawl company website (homepage + subpages: /about, /team, /contact).
    Returns dict with extracted email, decision_maker, decision_title, social links.
    """
    result = {
        "email": None,
        "decision_maker": None,
        "decision_title": None,
        "linkedin_url": None,
        "facebook_url": None,
        "instagram_url": None,
        "has_quote_form": False,
        "raw_snippet": ""
    }

    if not website_url or not website_url.startswith("http"):
        return result

    base_url = website_url.rstrip("/")

    # Subpages to check
    subpages = ["", "/about", "/about-us", "/our-team", "/team", "/contact", "/contact-us", "/leadership"]

    crawled_urls = set()
    all_text = ""

    for sub in subpages:
        target_url = base_url + sub if sub else base_url
        if target_url in crawled_urls:
            continue
        crawled_urls.add(target_url)

        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=7, allow_redirects=True)
            if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
                soup = BeautifulSoup(resp.text, "html.parser")

                # Remove scripts and styles
                for s in soup(["script", "style", "header", "footer", "nav"]):
                    s.decompose()

                text = soup.get_text(separator=" ", strip=True)
                all_text += " " + text

                # Check quote form
                if any(w in text.lower() for w in ["quote", "request a quote", "estimate", "get in touch", "contact us"]):
                    result["has_quote_form"] = True

                # Extract emails
                if not result["email"]:
                    emails = EMAIL_RE.findall(resp.text)
                    for em in emails:
                        if not any(ignore in em.lower() for ignore in ["sentry", "wix", "domain", "example", "schema", "png", "jpg"]):
                            result["email"] = em
                            break

                # Extract executive name from text
                if not result["decision_maker"]:
                    m_after = NAME_AFTER_TITLE_RE.search(text)
                    if m_after:
                        result["decision_maker"] = m_after.group(1)
                        result["decision_title"] = "Executive / Owner"
                    else:
                        m_before = NAME_BEFORE_TITLE_RE.search(text)
                        if m_before:
                            result["decision_maker"] = m_before.group(1)
                            result["decision_title"] = "Executive / Owner"

                # Extract social links
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "linkedin.com/company" in href or "linkedin.com/in" in href:
                        result["linkedin_url"] = href
                    elif "facebook.com" in href and not result["facebook_url"]:
                        result["facebook_url"] = href
                    elif "instagram.com" in href and not result["instagram_url"]:
                        result["instagram_url"] = href

        except Exception:
            continue

    result["raw_snippet"] = all_text[:500] if all_text else ""
    return result
