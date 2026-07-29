# ============================================================
# layer1_discovery.py — Wide Net Crawl
# Discover config.DISCOVERY_TARGET+ raw business leads across
# DuckDuckGo, the local.ch directory, and Maps-indexed listings.
# Every outbound search goes through utils.net.ddgs_gate (or the
# rate-limited SearchChClient), so this layer can never hang the
# pipeline — every call is timeout-bounded and circuit-broken.
# ============================================================

import asyncio
import random
import re
import time
from typing import Any, Dict, List, Set, Tuple

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn

import config
from utils.logger import get_logger
from utils.net import ddgs_gate
from utils.phone import normalize_swiss_phone
from utils.state_manager import check_cancellation

logger = get_logger("layer1")
console = Console()

# Reverse lookup built once: city name (lowercase) -> canton.
_CITY_TO_CANTON = {
    city.lower(): canton
    for canton, cities in config.CANTON_CITIES.items()
    for city in cities
}


def clean_company_title(title: str) -> str:
    """DDGS titles are raw SEO page titles, not clean business names — real examples
    seen live: 'Plombier sanitaire Montreux | 021 505 01 21 | Devis Gratuit ...',
    'Schaeffer SA – Chauffages à Fribourg | local.chClimatisation ...'. Keep only
    the leading segment before the first pipe/dash separator, which is
    consistently the actual business/page name. Not perfect (an occasional news
    headline slips through), but removes the worst offenders — trailing phone
    numbers, taglines, and concatenated second titles."""
    title = title.strip()
    title = re.split(r"\s*\|\s*", title)[0]
    title = re.split(r"\s[–—]\s", title)[0]
    return title.strip()[:80]


def normalize_name(s: str) -> str:
    """Normalize company name for deduplication."""
    if not s:
        return ""
    s = s.lower().strip()
    for suffix in [" sa", " sàrl", " sarl", " gmbh", " ag", " & cie", " et cie"]:
        s = s.replace(suffix, "")
    return re.sub(r'\W+', '', s)


def extract_phones(text: str) -> List[str]:
    """Extract Swiss phone numbers from text."""
    patterns = [
        r'(\+41\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2})',
        r'(0\d{2}\s?\d{3}\s?\d{2}\s?\d{2})',
        r'(\+41\s?\(\d{2}\)\s?\d{3}\s?\d{2}\s?\d{2})',
    ]
    phones = []
    for pattern in patterns:
        phones.extend(re.findall(pattern, text))
    return phones


def detect_canton(text: str, city: str = "") -> str:
    """Detect canton from known city names appearing in text (fallback only —
    prefer the canton/city known from query context when available)."""
    haystack = (text + " " + city).lower()
    for canton, cities in config.CANTON_CITIES.items():
        for c in cities:
            if c.lower() in haystack:
                return canton
    return ""


# All trade-relevant keywords that make a result worth keeping.
# This is the definitive list: if NONE of these appear in a search result's
# title+body, the result is discarded in Layer 1 before entering the pipeline.
_TRADE_KEYWORDS = {
    "plomberie": ["plombier", "plomberie", "tuyauterie", "débouchage", "debouchage",
                  "canalisation", "canalisations", "fuite d'eau"],
    "sanitaire": ["sanitaire", "installateur sanitaire", "installation sanitaire",
                  "installations sanitaires", "salle de bain", "robinetterie",
                  "génie sanitaire", "genie sanitaire", "robinet"],
    "chauffage": ["chauffagiste", "chauffage", "hvac", "thermique", "chaudière",
                  "chaudiere", "calorifère", "pompe à chaleur", "pompe a chaleur",
                  "installation thermique", "technique du bâtiment", "haustechnik",
                  "wärmetechnik", "warmetechnik", "climatisation", "ventilation"],
}

# Flat set of all keywords for fast membership testing
_ALL_TRADE_KEYWORDS: set = {kw for kws in _TRADE_KEYWORDS.values() for kw in kws}


def is_trade_relevant(text: str) -> bool:
    """Return True only if the text contains at least one genuine trade keyword.
    This is the permanent gate that prevents airports, restaurants, car dealers,
    public transport, and escort ads from entering the pipeline at all."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _ALL_TRADE_KEYWORDS)


def detect_niche(text: str) -> str:
    """Detect business niche from text. Returns "" if no trade keyword found.
    IMPORTANT: Never returns a fallback niche — an empty string means this result
    is NOT a plumbing/heating company and must be rejected by Layer 2."""
    text_lower = text.lower()
    for niche, keywords in _TRADE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return niche
    return ""  # No fallback — empty means not a trade business


_DDGS_LOOP_TIME_BUDGET = 180  # wall-clock ceiling for the whole query loop — see layer4_recrawl.py for why
# local.ch normally does most of the productive work here (every result already
# has a verified phone), so it gets a longer leash than DDGS — but it still needs
# a ceiling: verified live that local.ch can have a genuinely slow day (real
# per-page read timeouts observed), and without this, one bad day for the source
# we lean on most heavily could silently starve the whole discovery layer.
_DIRECTORY_TIME_BUDGET = 300


async def _search_ddgs(queries: List[Tuple[str, str, str]], target: int) -> List[Dict[str, Any]]:
    """Run DuckDuckGo searches. Each query carries the (canton, city) it targets, so
    results are tagged from known query context — not guessed from noisy snippet text."""
    leads = []
    start = time.time()

    async def _one_query(query: str, canton_hint: str, city_hint: str) -> List[Dict[str, Any]]:
        check_cancellation()
        results = await ddgs_gate.search(query, max_results=15)
        found = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            link = r.get("href", "")
            full_text = f"{title} {body}"

            # HARD GATE: reject results with no trade keyword whatsoever.
            # This is the permanent fix that stops airports, restaurants, car
            # dealers, SBB train stations, pharmacies, and escort listings from
            # ever entering the pipeline, regardless of downstream filters.
            if not is_trade_relevant(full_text):
                continue

            phones = extract_phones(full_text)
            phone = phones[0] if phones else ""
            if not normalize_swiss_phone(phone):
                continue

            niche = detect_niche(full_text)
            if not niche:
                # detect_niche returns "" for non-trade results — double-check
                # after is_trade_relevant just to be safe.
                continue

            found.append({
                "company_name": clean_company_title(title),
                "phone": phone,
                "website": link,
                "city": city_hint,
                "canton": canton_hint or detect_canton(full_text),
                "niche": niche,
                "source": "ddgs",
                "raw_snippet": body[:500],
            })
        return found

    # Fire queries in small concurrent batches instead of one at a time — this
    # doesn't raise the actual request rate (ddgs_gate's own semaphore/pacing/
    # circuit-breaker still gate every real call identically either way), it just
    # stops the caller from idling while ONE query's results get parsed before the
    # next query is even sent.
    batch_size = max(1, config.NET_MAX_CONCURRENT_DDGS)

    with Progress(TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TextColumn("{task.completed}/{task.total}")) as progress:
        task = progress.add_task("DuckDuckGo searches...", total=len(queries))

        for i in range(0, len(queries), batch_size):
            if len(leads) >= target:
                logger.info(f"Reached DDGS target ({target} leads), stopping DDGS search early.")
                break
            if time.time() - start > _DDGS_LOOP_TIME_BUDGET:
                logger.info(f"DDGS time budget ({_DDGS_LOOP_TIME_BUDGET}s) reached — "
                            f"moving on with {len(leads)} leads found so far.")
                break

            chunk = queries[i:i + batch_size]
            chunk_results = await asyncio.gather(*(_one_query(q, ch, ci) for q, ch, ci in chunk))
            for found in chunk_results:
                leads.extend(found)
            progress.advance(task, advance=len(chunk))

    return leads


_DIRECTORY_CONCURRENCY = 6  # concurrent local.ch city-queries. SearchChClient's rate
# limiter is a shared, thread-safe lock (see utils/search_ch.py), so this does NOT
# raise the actual request rate to local.ch — real requests still queue >= 2s apart
# no matter how many of these run "at once". What it buys is overlap: while one
# query's HTML is being parsed (or its thread is mid-wait on the rate limiter),
# another query's request can already be in flight, instead of the whole layer
# sitting idle between them.


async def _search_directory(niches: List[str], cantons: List[str], target: int) -> List[Dict[str, Any]]:
    """Search the local.ch directory (via SearchChClient) for businesses."""
    leads: List[Dict[str, Any]] = []

    try:
        from utils.search_ch import SearchChClient
    except ImportError:
        logger.warning("search_ch module not available, skipping directory search")
        return leads

    client = SearchChClient(config.SEARCH_CH_API_KEY)
    start = time.time()

    # Every city, not just the first 8 — Genève and Vaud each have 10 configured
    # cities, so the old [:8] cap silently skipped 2 of them on every single
    # Layer 1 pass. The _DIRECTORY_TIME_BUDGET below is still the real ceiling
    # on how much of this gets tried, so widening this doesn't cost anything —
    # it just means the budget is spent on genuinely full coverage instead of
    # always missing the same handful of cities.
    combos: List[Tuple[str, str, str]] = [
        (niche, canton, city)
        for niche in niches
        for canton in cantons
        for city in config.CANTON_CITIES.get(canton, [canton])
    ]

    async def _one_combo(niche: str, canton: str, city: str) -> List[Dict[str, Any]]:
        check_cancellation()
        try:
            # Each call fans out into up to 10 sequential detail-page fetches,
            # each with its own network round-trip plus a deliberate 0.6-1.2s
            # politeness delay — 9-30s+ in practice even when everything is
            # working normally (verified live: real batches routinely land at
            # ~27-30s). A shorter timeout doesn't actually save time either,
            # since asyncio.wait_for can't kill the underlying OS thread — it
            # just abandons the results while the thread keeps scraping to
            # completion in the background, so every "timeout" was silently
            # discarding real, already-found leads.
            results = await asyncio.wait_for(
                asyncio.to_thread(client.search, niche, city, 10), timeout=60
            )
        except Exception as e:
            logger.warning(f"local.ch directory error for {niche} in {city}: {e}")
            return []

        return [{
            "company_name": r.get("name", ""),
            "phone": r.get("phone", ""),
            "email": r.get("email", ""),
            "website": r.get("website", ""),
            "city": r.get("city", city),
            "postal_code": r.get("postal_code", ""),
            "address": r.get("address", ""),
            "canton": r.get("canton") or canton,
            "niche": detect_niche(r.get("category", "")) or detect_niche(niche) or niche,
            "source": "search.ch",
            "raw_snippet": r.get("category", ""),
        } for r in results]

    try:
        for i in range(0, len(combos), _DIRECTORY_CONCURRENCY):
            if len(leads) >= target:
                return leads
            if time.time() - start > _DIRECTORY_TIME_BUDGET:
                logger.info(f"local.ch directory time budget ({_DIRECTORY_TIME_BUDGET}s) reached — "
                            f"moving on with {len(leads)} leads found so far.")
                return leads

            chunk = combos[i:i + _DIRECTORY_CONCURRENCY]
            chunk_results = await asyncio.gather(*(_one_combo(n, c, ci) for n, c, ci in chunk))
            for found in chunk_results:
                leads.extend(found)
    finally:
        client.close()

    return leads


async def _search_maps(niches: List[str], cities: List[str], target: int) -> List[Dict[str, Any]]:
    """Search for businesses via DuckDuckGo, targeting Google Maps listings."""
    leads: List[Dict[str, Any]] = []
    queries: List[Tuple[str, str, str]] = []

    for niche in niches[:4]:
        for city in cities[:10]:
            canton_hint = _CITY_TO_CANTON.get(city.lower(), "")
            queries.append((f"{niche} {city} site:google.com/maps", canton_hint, city))

    random.shuffle(queries)
    start = time.time()
    queries = queries[:50]
    batch_size = max(1, config.NET_MAX_CONCURRENT_DDGS)  # see _search_ddgs

    async def _one_query(query: str, canton_hint: str, city_hint: str) -> List[Dict[str, Any]]:
        check_cancellation()
        results = await ddgs_gate.search(query, max_results=5)
        found = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            full_text = f"{title} {body}"

            # Same hard gate as in _search_ddgs — no trade keyword = not entered
            if not is_trade_relevant(full_text):
                continue

            phones = extract_phones(full_text)
            phone = phones[0] if phones else ""
            if not normalize_swiss_phone(phone):
                continue

            niche = detect_niche(full_text)
            if not niche:
                continue

            found.append({
                "company_name": clean_company_title(title),
                "phone": phone,
                "website": r.get("href", ""),
                "city": city_hint,
                "canton": canton_hint or detect_canton(full_text),
                "niche": niche,
                "source": "ddgs_maps",
                "raw_snippet": body[:500],
            })
        return found

    for i in range(0, len(queries), batch_size):
        if len(leads) >= target:
            logger.info(f"Reached Maps target ({target} leads), stopping Maps search early.")
            break
        if time.time() - start > _DDGS_LOOP_TIME_BUDGET:
            logger.info(f"Maps time budget ({_DDGS_LOOP_TIME_BUDGET}s) reached — "
                        f"moving on with {len(leads)} leads found so far.")
            break

        chunk = queries[i:i + batch_size]
        chunk_results = await asyncio.gather(*(_one_query(q, ch, ci) for q, ch, ci in chunk))
        for found in chunk_results:
            leads.extend(found)

    return leads


def _deduplicate(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate by phone AND by normalized company name — checked
    independently, not "phone if present else name". A single small trade
    business commonly surfaces under more than one real phone number (the shop
    landline in one listing, the owner's mobile in another); comparing only
    phone would let the same company through twice under those two numbers.
    Also skips anything already blacklisted, by phone OR by name, so a company
    fully processed in a past run can't reappear as an apparently-new lead
    just because this listing surfaced a different number for it."""
    from utils.database import is_blacklisted, is_blacklisted_by_name

    seen_phones: Set[str] = set()
    seen_names: Set[str] = set()
    unique = []

    for lead in leads:
        name_key = normalize_name(lead.get("company_name", ""))
        # Normalize to E.164 before comparing — the blacklist always stores
        # E.164 (that's what lead["phone"] holds by the time Layer 6 writes
        # it), but at THIS point in the pipeline phone is still raw text
        # straight from a search snippet ("022 886 02 26"). Comparing that
        # raw form against an E.164-stored blacklist entry silently never
        # matches, even for the exact same real number. Falls back to the
        # whitespace-stripped raw string only when normalization fails
        # (invalid/foreign number), so there's still SOME dedup key.
        raw_phone = lead.get("phone", "")
        phone_key = normalize_swiss_phone(raw_phone) or re.sub(r'\s+', '', raw_phone)

        if not phone_key and not name_key:
            continue
        if phone_key and phone_key in seen_phones:
            continue
        if name_key and name_key in seen_names:
            continue
        if phone_key and is_blacklisted(phone_key):
            continue
        if name_key and is_blacklisted_by_name(name_key):
            continue

        if phone_key:
            seen_phones.add(phone_key)
        if name_key:
            seen_names.add(name_key)
        unique.append(lead)

    return unique


async def discover_accounts() -> List[Dict[str, Any]]:
    """
    Main discovery function — Layer 1.
    Crawls config.DISCOVERY_TARGET+ raw business leads using multiple sources.
    """
    console.print("[bold cyan]🔍 Layer 1: Starting wide-net discovery...[/bold cyan]")

    target = config.DISCOVERY_TARGET
    # Soft per-source caps. local.ch gets the largest share on purpose: every lead
    # it returns already has a verified phone number (the scraper skips listings
    # without one), so it survives Layer 2 filtering at a far higher rate than DDGS
    # snippets, which frequently have no extractable phone at all. Leaning on it
    # heavily means Layer 1 alone can usually reach TARGET_LEAD_COUNT without ever
    # needing the slower Layer 4 recrawl. DDGS/Maps stay in as supplementary
    # sources — useful when they're not rate-limited, harmless when they are.
    directory_target = int(target * 0.9)
    ddgs_target = int(target * 0.3)
    maps_target = int(target * 0.15)

    # Every configured niche, not just the primary 8 — SECONDARY_NICHES (couvreur,
    # électricien, and the adjacent trades added to widen the addressable market)
    # used to only get searched during Layer 4 recrawl, meaning Layer 1's own
    # first pass was silently narrower than the full target market on every run.
    all_niches = config.PRIMARY_NICHES + config.SECONDARY_NICHES

    # Build DDGS queries, each carrying the (canton, city) it targets — so results
    # are tagged reliably instead of relying on snippet text mentioning the city.
    ddgs_queries: List[Tuple[str, str, str]] = []
    for niche in all_niches:
        for canton in config.TARGET_CANTONS:
            ddgs_queries.append((f"{niche} {canton}", canton, ""))
            ddgs_queries.append((f"{niche} site:local.ch {canton}", canton, ""))
        for canton, cities in config.CANTON_CITIES.items():
            for city in cities[:3]:
                ddgs_queries.append((f"{niche} {city}", canton, city))
                ddgs_queries.append((f"{niche} {city} téléphone", canton, city))

    random.shuffle(ddgs_queries)
    ddgs_queries = ddgs_queries[:150]

    all_cities = [city for cities in config.CANTON_CITIES.values() for city in cities]

    console.print(f"  → {len(ddgs_queries)} DuckDuckGo queries (target {ddgs_target} leads)")
    console.print(f"  → {len(all_niches)} niches × {len(config.TARGET_CANTONS)} cantons via local.ch (target {directory_target} leads)")
    console.print(f"  → Maps search for top cities (target {maps_target} leads)")

    ddgs_leads, directory_leads, maps_leads = await asyncio.gather(
        _search_ddgs(ddgs_queries, ddgs_target),
        _search_directory(all_niches, config.TARGET_CANTONS, directory_target),
        _search_maps(all_niches, all_cities, maps_target),
    )

    all_leads = ddgs_leads + directory_leads + maps_leads
    console.print(f"\n  Raw total: {len(all_leads)} (DDGS: {len(ddgs_leads)}, Directory: {len(directory_leads)}, Maps: {len(maps_leads)})")

    unique_leads = _deduplicate(all_leads)
    console.print(f"  After dedup: {len(unique_leads)} unique leads (target was {target}+)")

    return unique_leads
