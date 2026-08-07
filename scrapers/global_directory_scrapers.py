# ============================================================
# global_directory_scrapers.py — Standalone Free Directory Scrapers
# Supports USA 🇺🇸, United Kingdom 🇬🇧, Canada 🇨🇦, Australia 🇦🇺
# ============================================================

import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

PHONE_EXTRACT_RE = re.compile(r"(\+?\d{1,4}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4})")

def scrape_ddgs_country(keyword: str, location: str, country_code: str) -> List[Dict[str, Any]]:
    """Use DuckDuckGo search to extract trade contractor candidates for US, UK, CA, AU"""
    results = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        region_map = {"US": "us-en", "GB": "uk-en", "CA": "ca-en", "AU": "au-en"}
        reg = region_map.get(country_code, "us-en")

        query = f"{keyword} {location} phone"
        with DDGS() as ddgs:
            raw_res = list(ddgs.text(query, region=reg, max_results=8))

            for r in raw_res:
                title = r.get("title", "")
                href = r.get("href", "")
                body = r.get("body", "")

                comp_name = title.split("-")[0].split("|")[0].split(":")[0].strip()
                phones = PHONE_EXTRACT_RE.findall(f"{title} {body}")
                phone = phones[0] if phones else ""

                if comp_name and len(comp_name) > 3:
                    results.append({
                        "company_name": comp_name,
                        "phone": phone,
                        "website": href,
                        "niche": keyword,
                        "canton": location,
                        "city": location,
                        "raw_snippet": body[:300],
                        "source": f"ddgs_{country_code.lower()}"
                    })
    except Exception as e:
        print(f"DDGS country scraper error for {country_code}: {e}")

    return results

# ── 1. USA Scraper (YellowPages US) ─────────────────────────

def scrape_yellowpages_us(keyword: str, location: str) -> List[Dict[str, Any]]:
    """Scrape free US business listings from YellowPages.com"""
    results = []
    kw_quote = urllib.parse.quote_plus(keyword)
    loc_quote = urllib.parse.quote_plus(location)
    url = f"https://www.yellowpages.com/search?search_terms={kw_quote}&geo_location_terms={loc_quote}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            listings = soup.select('.result')
            for item in listings:
                name_elem = item.select_one('.business-name')
                phone_elem = item.select_one('.phones')
                street_elem = item.select_one('.street-address')
                locality_elem = item.select_one('.locality')
                web_elem = item.select_one('.track-visit-website')

                if name_elem:
                    comp_name = name_elem.get_text(strip=True)
                    phone = phone_elem.get_text(strip=True) if phone_elem else ""
                    address = street_elem.get_text(strip=True) if street_elem else ""
                    if locality_elem:
                        address += " " + locality_elem.get_text(strip=True)
                    website = web_elem['href'] if web_elem and web_elem.has_attr('href') else ""

                    results.append({
                        "company_name": comp_name,
                        "phone": phone,
                        "address": address,
                        "website": website,
                        "niche": keyword,
                        "canton": location.split(',')[-1].strip() if ',' in location else location,
                        "city": location.split(',')[0].strip(),
                        "source": "yellowpages_us"
                    })
    except Exception as e:
        print(f"YellowPages US error: {e}")

    return results


# ── 2. UK Scraper (Yell.com) ──────────────────────────────────
def scrape_yell_uk(keyword: str, location: str) -> List[Dict[str, Any]]:
    """Scrape free UK business listings from Yell.com"""
    results = []
    kw_quote = urllib.parse.quote_plus(keyword)
    loc_quote = urllib.parse.quote_plus(location)
    url = f"https://www.yell.com/ucs/UcsKeywordSeap.do?keywords={kw_quote}&location={loc_quote}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.select('article.businessCapsule')
            for item in articles:
                name_elem = item.select_one('.businessCapsule--title')
                phone_elem = item.select_one('.business--telephoneNumber')
                addr_elem = item.select_one('.businessCapsule--address')
                web_elem = item.select_one('a[btn-website]')

                if name_elem:
                    comp_name = name_elem.get_text(strip=True)
                    phone = phone_elem.get_text(strip=True) if phone_elem else ""
                    address = addr_elem.get_text(strip=True) if addr_elem else ""
                    website = web_elem['href'] if web_elem and web_elem.has_attr('href') else ""

                    results.append({
                        "company_name": comp_name,
                        "phone": phone,
                        "address": address,
                        "website": website,
                        "niche": keyword,
                        "canton": location,
                        "city": location,
                        "source": "yell_uk"
                    })
    except Exception as e:
        print(f"Yell UK error: {e}")

    return results


# ── 3. Canada Scraper (YellowPages CA) ────────────────────────
def scrape_yellowpages_ca(keyword: str, location: str) -> List[Dict[str, Any]]:
    """Scrape free Canadian business listings from YellowPages.ca"""
    results = []
    kw_quote = urllib.parse.quote_plus(keyword)
    loc_quote = urllib.parse.quote_plus(location)
    url = f"https://www.yellowpages.ca/search/si/1/{kw_quote}/{loc_quote}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            listings = soup.select('.listing')
            for item in listings:
                name_elem = item.select_one('.listing__name')
                phone_elem = item.select_one('.mlr__item--phone')
                addr_elem = item.select_one('.listing__address')

                if name_elem:
                    comp_name = name_elem.get_text(strip=True)
                    phone = phone_elem.get_text(strip=True) if phone_elem else ""
                    address = addr_elem.get_text(strip=True) if addr_elem else ""

                    results.append({
                        "company_name": comp_name,
                        "phone": phone,
                        "address": address,
                        "niche": keyword,
                        "canton": location,
                        "city": location,
                        "source": "yellowpages_ca"
                    })
    except Exception as e:
        print(f"YellowPages CA error: {e}")

    return results


# ── 4. Australia Scraper (YellowPages AU) ─────────────────────
def scrape_yellowpages_au(keyword: str, location: str) -> List[Dict[str, Any]]:
    """Scrape free Australian business listings from YellowPages.com.au"""
    results = []
    kw_quote = urllib.parse.quote_plus(keyword)
    loc_quote = urllib.parse.quote_plus(location)
    url = f"https://www.yellowpages.com.au/search/listings?clue={kw_quote}&locationClue={loc_quote}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            cards = soup.select('.search-contact-card')
            for item in cards:
                name_elem = item.select_one('.listing-name')
                phone_elem = item.select_one('.contact-phone')
                addr_elem = item.select_one('.building-address')

                if name_elem:
                    comp_name = name_elem.get_text(strip=True)
                    phone = phone_elem.get_text(strip=True) if phone_elem else ""
                    address = addr_elem.get_text(strip=True) if addr_elem else ""

                    results.append({
                        "company_name": comp_name,
                        "phone": phone,
                        "address": address,
                        "niche": keyword,
                        "canton": location,
                        "city": location,
                        "source": "yellowpages_au"
                    })
    except Exception as e:
        print(f"YellowPages AU error: {e}")

    return results


# ── 5. OpenStreetMap Overpass API (Free Geographic Query) ───
def scrape_overpass_osm(country_code: str, keyword: str) -> List[Dict[str, Any]]:
    """Query OpenStreetMap Overpass API for commercial trade contractors"""
    results = []
    osm_query = f"""
    [out:json][timeout:15];
    area["ISO3166-1"="{country_code}"]->.searchArea;
    (
      node["craft"](area.searchArea);
      way["craft"](area.searchArea);
    );
    out body 20;
    """
    try:
        resp = requests.post("https://overpass-api.de/api/interpreter", data={"data": osm_query}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for element in data.get("elements", []):
                tags = element.get("tags", {})
                name = tags.get("name")
                phone = tags.get("phone") or tags.get("contact:phone")
                website = tags.get("website") or tags.get("contact:website")
                city = tags.get("addr:city") or tags.get("addr:suburb") or ""

                if name:
                    results.append({
                        "company_name": name,
                        "phone": phone or "",
                        "website": website or "",
                        "city": city,
                        "canton": tags.get("addr:state") or city,
                        "niche": keyword,
                        "source": "overpass_osm"
                    })
    except Exception as e:
        print(f"OSM Overpass error: {e}")

    return results


# ── 6. Australia Business Register ABN Lookup API (Free Official API) ──
def search_australian_abn(business_name: str) -> List[Dict[str, Any]]:
    """Search free Australian Business Register (ABN) API for official business names and directors"""
    results = []
    url = f"https://abr.business.gov.au/json/MatchingNames.aspx?name={urllib.parse.quote_plus(business_name)}&guid=test"
    try:
        resp = requests.get(url, timeout=7)
        if resp.status_code == 200:
            text = resp.text
            if "callback(" in text:
                text = text[text.find("(") + 1 : text.rfind(")")]
            import json
            data = json.loads(text)
            for item in data.get("Names", []):
                results.append({
                    "company_name": item.get("Name"),
                    "abn": item.get("Abn"),
                    "state": item.get("State"),
                    "postcode": item.get("Postcode"),
                    "source": "abn_lookup_au"
                })
    except Exception as e:
        print(f"ABN Lookup AU error: {e}")

    return results

