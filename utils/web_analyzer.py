# ============================================================
# web_analyzer.py — Public-Info Website Analyzer
# Crawls a company's own website (homepage + a few relevant
# subpages) via plain HTTP + BeautifulSoup and extracts every
# publicly-observable signal Layer 5/6 need: SSL, quote-form
# presence, social links, tech stack, decision-maker candidate
# text, etc. No AI, no headless browser — just parsing what the
# site actually publishes, which keeps it fast and impossible
# to hang past its per-request timeout.
# ============================================================

import re
from typing import Any, Dict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from config import BOOKING_SIGNALS
from utils.logger import get_logger
from utils.net import safe_get

logger = get_logger("WebAnalyzer")

# Subpage link hints we try to follow, in priority order (French-first, Swiss trade sites).
_SUBPAGE_HINTS = [
    ("contact", ["contact", "nous-contacter", "nous contacter"]),
    ("devis", ["devis", "demande-de-devis", "obtenir-une-offre", "demander-une-offre"]),
    ("services", ["services", "prestations", "nos-services"]),
    ("about", ["a-propos", "à-propos", "à propos", "qui-sommes-nous", "notre-entreprise",
               "equipe", "team", "impressum", "mentions-legales"]),
]

_TITLE_KEYWORDS = [
    "directeur", "directrice", "gérant", "gérante", "fondateur", "fondatrice",
    "propriétaire", "responsable technique", "responsable d'entreprise", "associé", "associée",
    "administrateur", "ceo", "chef d'entreprise", "patron",
]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_COPYRIGHT_YEAR_RE = re.compile(r"(?:©|copyright|\(c\))\s*(\d{4})", re.IGNORECASE)
_JUNK_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

# A headcount the company states about itself: "notre équipe de 12 collaborateurs",
# "plus de 20 employés", "une équipe de 8 spécialistes". This is the closest thing
# to a real employee number we can get — used directly by utils/company_size.py.
_STAFF_COUNT_RE = re.compile(
    r"(\d{1,3})\s*(?:\+)?\s*"
    r"(?:employ[ée]s?|collaborateur|collaboratrice|salari[ée]s?|personnes?|"
    r"technicien|sp[ée]cialistes?|monteur|installateur|ouvrier|mitarbeiter|"
    r"besch[äa]ftigte|angestellte)",
    re.IGNORECASE,
)
# Softer signal: the site talks about a team at all (a plausible >1-person shop).
_TEAM_MENTION_RE = re.compile(
    r"(notre\s+[ée]quipe|nos\s+collaborateurs|notre\s+team|unser\s+team|"
    r"unser\s+mitarbeiter|nos\s+techniciens|notre\s+personnel|rejoignez[- ]nous|"
    r"nous\s+recrutons|offres?\s+d['e ]emploi)",
    re.IGNORECASE,
)


def _parse_page(html: str) -> Dict[str, Any]:
    """Extract every signal we can from a single fetched page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    text_lower = text.lower()
    html_lower = html.lower()

    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = (meta_desc_tag.get("content", "") if meta_desc_tag else "") or ""

    has_viewport = soup.find("meta", attrs={"name": "viewport"}) is not None

    emails = {e for e in _EMAIL_RE.findall(text) if not e.lower().endswith(_JUNK_EMAIL_SUFFIXES)}

    has_quote_form = any(signal in text_lower for signal in BOOKING_SIGNALS)
    has_booking_system = any(k in text_lower for k in ("calendly", "doodle.com", "agenda en ligne", "prise de rendez-vous en ligne"))

    social_links: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lower = href.lower()
        if "instagram.com" in href_lower:
            social_links.setdefault("instagram", href)
        elif "facebook.com" in href_lower:
            social_links.setdefault("facebook", href)
        elif "linkedin.com" in href_lower:
            social_links.setdefault("linkedin", href)

    tech_stack = []
    if "wp-content" in html_lower or "wordpress" in html_lower:
        tech_stack.append("WordPress")
    if "cdn.shopify.com" in html_lower:
        tech_stack.append("Shopify")
    if "static.wixstatic.com" in html_lower or ("wix.com" in html_lower and "wixsite" in html_lower):
        tech_stack.append("Wix")
    if "webflow.com" in html_lower or "webflow.io" in html_lower:
        tech_stack.append("Webflow")
    if "squarespace.com" in html_lower:
        tech_stack.append("Squarespace")
    if "jimdo" in html_lower:
        tech_stack.append("Jimdo")

    copyright_years = [int(y) for y in _COPYRIGHT_YEAR_RE.findall(text)]

    # Staff-size signals (see utils/company_size.py). A self-published headcount
    # is the strongest; a plausible cap of 500 guards against catching an address
    # number or a phone fragment that happened to precede a staff word.
    staff_counts = [int(m) for m in _STAFF_COUNT_RE.findall(text) if int(m) <= 500]
    team_headcount_hint = max(staff_counts) if staff_counts else None
    mentions_team = bool(_TEAM_MENTION_RE.search(text))

    # Lines mentioning a decision-maker title — candidate text for Layer 6 name extraction.
    dm_candidates = []
    for line in re.split(r"[\n\r]+|(?<=[.!?])\s{2,}", text):
        line = line.strip()
        if not line or len(line) > 200:
            continue
        if any(kw in line.lower() for kw in _TITLE_KEYWORDS):
            dm_candidates.append(line)

    # Links worth following next.
    subpage_links: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        link_text = (a.get_text() or "").strip().lower()
        haystack = f"{href.lower()} {link_text}"
        for label, hints in _SUBPAGE_HINTS:
            if label in subpage_links:
                continue
            if any(h in haystack for h in hints):
                subpage_links[label] = href

    return {
        "has_quote_form": has_quote_form,
        "has_booking_system": has_booking_system,
        "meta_description": meta_description,
        "has_viewport": has_viewport,
        "emails": emails,
        "social_links": social_links,
        "tech_stack": tech_stack,
        "copyright_years": copyright_years,
        "dm_candidates": dm_candidates,
        "team_headcount_hint": team_headcount_hint,
        "mentions_team": mentions_team,
        "word_count": len(text.split()),
        "subpage_links": subpage_links,
    }


def _merge(result: Dict[str, Any], parsed: Dict[str, Any], emails_acc: set) -> None:
    result["has_quote_form"] = result["has_quote_form"] or parsed["has_quote_form"]
    result["has_booking_system"] = result["has_booking_system"] or parsed["has_booking_system"]
    result["has_viewport"] = result["has_viewport"] or parsed["has_viewport"]
    if not result["meta_description"]:
        result["meta_description"] = parsed["meta_description"]
    emails_acc.update(parsed["emails"])
    for k, v in parsed["social_links"].items():
        result["social_links"].setdefault(k, v)
    for t in parsed["tech_stack"]:
        if t not in result["tech_stack"]:
            result["tech_stack"].append(t)
    if parsed["copyright_years"]:
        latest = max(parsed["copyright_years"])
        if result["last_copyright_year"] is None or latest > result["last_copyright_year"]:
            result["last_copyright_year"] = latest
    for line in parsed["dm_candidates"]:
        if line not in result["decision_maker_candidates"] and len(result["decision_maker_candidates"]) < 20:
            result["decision_maker_candidates"].append(line)
    # Staff signals: keep the largest published headcount seen across pages, and
    # OR the team-mention flag (an 'équipe'/'collaborateurs' page is often a subpage).
    if parsed.get("team_headcount_hint"):
        if result["team_headcount_hint"] is None or parsed["team_headcount_hint"] > result["team_headcount_hint"]:
            result["team_headcount_hint"] = parsed["team_headcount_hint"]
    result["mentions_team"] = result["mentions_team"] or parsed.get("mentions_team", False)
    result["word_count"] += parsed["word_count"]


async def analyze_website(url: str, max_subpages: int = 3, timeout: float = 10.0) -> Dict[str, Any]:
    """Crawl a company's website (homepage + up to `max_subpages` relevant subpages)
    and return every publicly-observable signal as a plain dict. Pure HTTP+BS4 —
    no headless browser, no AI — so each page is bounded by `timeout` and the whole
    call can never hang the pipeline."""
    result: Dict[str, Any] = {
        "has_ssl": False,
        "has_quote_form": False,
        "has_booking_system": False,
        "meta_description": "",
        "has_viewport": False,
        "contact_emails": [],
        "social_links": {},
        "tech_stack": [],
        "last_copyright_year": None,
        "decision_maker_candidates": [],
        "team_headcount_hint": None,
        "mentions_team": False,
        "pages_crawled": 0,
        "word_count": 0,
        "reachable": False,
    }

    if not url:
        return result
    if not url.startswith("http"):
        url = "https://" + url

    resp = await safe_get(url, timeout=timeout)
    if resp is None or resp.status_code >= 400:
        return result

    result["reachable"] = True
    result["has_ssl"] = str(resp.url).startswith("https")
    result["pages_crawled"] = 1

    emails_acc: set = set()
    parsed = _parse_page(resp.text)
    _merge(result, parsed, emails_acc)

    domain = urlparse(str(resp.url)).netloc
    followed = 0
    for link in parsed["subpage_links"].values():
        if followed >= max_subpages:
            break
        absolute = urljoin(str(resp.url), link)
        if urlparse(absolute).netloc != domain:
            continue
        sub_resp = await safe_get(absolute, timeout=timeout)
        followed += 1
        if sub_resp is None or sub_resp.status_code >= 400:
            continue
        sub_parsed = _parse_page(sub_resp.text)
        _merge(result, sub_parsed, emails_acc)
        result["pages_crawled"] += 1

    result["contact_emails"] = sorted(emails_acc)
    return result
