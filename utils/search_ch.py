# ============================================================
# search_ch.py — Swiss Business Directory Client
# Uses the search.ch tel API when a key is configured, otherwise
# falls back to scraping local.ch's public directory.
#
# The local.ch fallback is built against the site's real structure
# (verified against a live fetch, not guessed):
#   - Listing page: <article class="xenon-entry-card"> cards whose
#     detail link is /fr/d/{city-slug}/{postal-code}/{niche-slug}/{slug}
#     — postal code and niche come free from the URL, no extra request.
#   - Detail page: a schema.org LocalBusiness JSON-LD block (canonical
#     name/address/postal code) plus <a data-testid="contact-link">
#     anchors for tel:/mailto:/website — all server-rendered, so a
#     plain GET is enough (no headless browser needed).
# ============================================================

import json
import random
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from config import CANTON_CITIES
from utils.logger import get_logger
from utils.state_manager import check_cancellation

logger = get_logger("SearchCh")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_SKIP_WEBSITE_DOMAINS = (
    "local.ch", "localsearch.ch", "search.ch", "google.", "apple.com",
    "facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "pinterest.com",
)


def _detect_canton_from_city(city: str) -> str:
    """Match a city name against the curated CANTON_CITIES map (case-insensitive, substring-tolerant)."""
    if not city:
        return ""
    city_lower = city.strip().lower()
    for canton, cities in CANTON_CITIES.items():
        for c in cities:
            c_lower = c.lower()
            if c_lower == city_lower or c_lower in city_lower or city_lower in c_lower:
                return canton
    return ""


class SearchChClient:
    """Client for the search.ch API and the local.ch directory scraper fallback."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or ""
        self.last_request_time = 0.0
        # Callers now run several of these searches concurrently (each in its own
        # asyncio.to_thread worker) to keep local.ch's rate-limited response time
        # from leaving the whole layer idle — this lock makes the shared
        # last_request_time check-and-update atomic across those threads, so the
        # real request cadence to local.ch stays exactly the same (still >= 2s
        # apart) no matter how many threads are waiting on it at once.
        self._rate_lock = threading.Lock()
        # One shared, connection-pooled client instead of a fresh httpx.Client()
        # per query — httpx.Client is documented safe for concurrent use from
        # multiple threads. Previously every one of the ~4 concurrent worker
        # threads opened (and DNS-resolved) its own client on every single call;
        # under sustained concurrent load that showed up live as a multi-minute
        # burst of "getaddrinfo failed" — reusing one client's connection pool
        # avoids re-resolving/re-connecting for every request.
        self._client = httpx.Client(timeout=15.0, follow_redirects=True, headers=HEADERS)
        if not self.api_key:
            logger.info("Initializing local.ch directory crawler fallback (no search.ch API key provided)")

    def close(self):
        self._client.close()

    def _wait_rate_limit(self):
        with self._rate_lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < 2.0:
                time.sleep(2.0 - elapsed)
            self.last_request_time = time.time()

    def search(self, query: str, location: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search the directory for a given query/location.
        Synchronous — callers must wrap this in asyncio.to_thread."""
        self._wait_rate_limit()

        if not self.api_key:
            return self._fallback_search(query, location, max_results)

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    "https://tel.search.ch/api/",
                    params={"key": self.api_key, "was": query, "wo": location,
                            "maxnum": max_results, "output": "json"},
                )
                response.raise_for_status()
                data = response.json()

            results = []
            for item in data.get("feed", {}).get("entry", [])[:max_results]:
                city = item.get("tel:city", "")
                results.append({
                    "name": item.get("title", {}).get("$t", ""),
                    "phone": item.get("tel:phone", ""),
                    "address": item.get("tel:street", ""),
                    "city": city,
                    # NOT "or location" — location here is the searched-for city (see the
                    # `where`/`wo` query param above), not a canton. Leaving it empty when
                    # detection fails lets the caller (which knows the real target canton)
                    # fall back correctly instead of a city silently becoming the canton.
                    "canton": _detect_canton_from_city(city),
                    "category": item.get("tel:category", ""),
                    "website": item.get("tel:link", ""),
                })
            return results
        except Exception as e:
            logger.error(f"search.ch API error: {e}")
            return []

    def _fallback_search(self, query: str, location: str, max_results: int) -> List[Dict[str, Any]]:
        """Scrape local.ch's public directory for businesses matching query/location."""
        search_url = f"https://www.local.ch/fr/q?what={quote(query)}&where={quote(location)}"
        logger.info(f"Querying local.ch directory: {query} in {location}")

        try:
            r = self._client.get(search_url, headers=HEADERS)
            if r.status_code != 200:
                logger.warning(f"local.ch directory returned status {r.status_code}")
                return []

            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.find_all("article", class_=lambda c: c and "xenon-entry-card" in c)

            results = []
            for article in articles[:max_results]:
                check_cancellation()

                h2 = article.find("h2")
                link_el = article.find("a", href=True)
                if not h2 or not link_el:
                    continue

                name = h2.get_text(strip=True)
                detail_path = link_el["href"]
                if not detail_path.startswith("/fr/d/"):
                    continue
                detail_url = f"https://www.local.ch{detail_path}"

                # City/postal code/niche ride along in the URL itself:
                # /fr/d/{city-slug}/{postal-code}/{niche-slug}/{company-slug}
                path_parts = detail_path.strip("/").split("/")
                url_city = path_parts[2].replace("-", " ").title() if len(path_parts) > 2 else ""
                url_postal = path_parts[3] if len(path_parts) > 3 and path_parts[3].isdigit() else ""
                url_niche = path_parts[4].replace("-", " ") if len(path_parts) > 4 else query

                lead = self._fetch_detail(self._client, detail_url, name, url_city, url_postal, url_niche)
                if lead:
                    results.append(lead)

                time.sleep(random.uniform(0.6, 1.2))

            return results
        except Exception as e:
            logger.error(f"local.ch scraping error: {e}")
            return []

    def _fetch_detail(self, client: httpx.Client, detail_url: str, fallback_name: str,
                       url_city: str, url_postal: str, url_niche: str) -> Optional[Dict[str, Any]]:
        """Fetch a single local.ch listing's detail page and extract verified contact data."""
        try:
            resp = client.get(detail_url, headers=HEADERS)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Canonical structured data — most reliable source of name/address/postal code.
            name, street, city, postal = fallback_name, "", url_city, url_postal
            ld_script = soup.find("script", attrs={"type": "application/ld+json"})
            if ld_script and ld_script.string:
                try:
                    data = json.loads(ld_script.string)
                    entries = data if isinstance(data, list) else [data]
                    for entry in entries:
                        if entry.get("@type") == "LocalBusiness":
                            name = entry.get("name") or name
                            addr = entry.get("address", {}) or {}
                            street = addr.get("streetAddress", "") or street
                            city = addr.get("addressLocality", "") or city
                            postal = addr.get("postalCode", "") or postal
                            break
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass

            # Contact info: tel:/mailto:/website all share data-testid="contact-link".
            phone, email, website = "", "", ""
            for a in soup.find_all("a", attrs={"data-testid": "contact-link"}, href=True):
                href = a["href"]
                if href.startswith("tel:") and not phone:
                    phone = href.replace("tel:", "").strip()
                elif href.startswith("mailto:") and not email:
                    email = href.replace("mailto:", "").strip()
                elif href.startswith("http") and not website:
                    if not any(d in href.lower() for d in _SKIP_WEBSITE_DOMAINS):
                        website = href

            if not phone:
                # No public phone number on file — not a usable lead.
                return None

            # NOT "or location" — this method is never passed the canton, only the city
            # that was searched for (see the removed `location` param). A city that isn't
            # in our curated CANTON_CITIES list must resolve to "", not silently become the
            # canton value — the caller falls back to the real target canton in that case.
            canton = _detect_canton_from_city(city) or _detect_canton_from_city(url_city)

            clean_name = "".join(c if ord(c) < 128 else "?" for c in name)
            logger.info(f"Scraped listing: {clean_name} (Phone: {phone})")

            return {
                "name": name,
                "phone": phone,
                "email": email,
                "address": ", ".join(p for p in [street, f"{postal} {city}".strip()] if p),
                "postal_code": postal,
                "city": city or url_city,
                "canton": canton,
                "category": url_niche,
                "website": website,
            }
        except Exception as e:
            logger.warning(f"Error fetching local.ch detail page {detail_url}: {e}")
            return None
