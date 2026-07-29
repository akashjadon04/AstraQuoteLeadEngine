# ============================================================
# layer4_recrawl.py — Adaptive Re-Crawl Loop
# Expands search when quota is not met. Uses TWO independent
# sources in parallel — DuckDuckGo (via the shared rate-limited/
# circuit-breakered gate) and the local.ch directory — so that if
# DuckDuckGo throttles or blocks outbound searches (it does, hard,
# under sustained load), this layer stays productive instead of
# stalling. Each result is tagged with the canton/city its query
# actually targeted instead of leaving canton blank (which used to
# let recrawled leads skip the Layer 2 region filter entirely).
#
# Callers pass in `used_queries`/`used_combos` sets that persist
# across the whole recrawl loop (see main.py) — every iteration
# draws only from territory not already tried THIS run, instead of
# reshuffling the same finite pool and rediscovering the same
# businesses iteration after iteration.
# ============================================================

import asyncio
import random
import re
import time
from typing import Any, Dict, List, Set, Tuple

from rich.console import Console

import config
from layers.layer1_discovery import clean_company_title, detect_canton, detect_niche, extract_phones, normalize_name, is_trade_relevant
from utils.database import is_blacklisted, is_blacklisted_by_name
from utils.logger import get_logger
from utils.net import ddgs_gate
from utils.phone import normalize_swiss_phone
from utils.state_manager import check_cancellation

logger = get_logger("layer4")
console = Console()


# Wall-clock ceiling for the WHOLE DDGS query loop, not just each individual call.
# Without this, a fully degraded/blocked DuckDuckGo (which happens under sustained
# load) forces this branch to grind through its queries one at a time — since
# recrawl() awaits both branches together, that would hold up the entire iteration
# for a very long time even after local.ch has already finished. Once the budget
# is hit, we return whatever was found so far instead of waiting out the rest.
_DDGS_LOOP_TIME_BUDGET = 180
_DIRECTORY_TIME_BUDGET = 200  # see layer1_discovery.py for why local.ch needs a ceiling too
_MAX_QUERIES_PER_ITERATION = 80
_MAX_DIRECTORY_COMBOS_PER_ITERATION = 60

# Query phrasing templates, cycled through as iterations climb — each contributes
# genuinely different search text, not just a reshuffle of the same terms.
_QUERY_TEMPLATES = [
    "{niche} {place}",
    "{niche} {place} téléphone",
    "{niche} {place} avis",
    "{niche} {place} devis",
    "{niche} {place} site:local.ch",
    "entreprise {niche} {place}",
    "société {niche} {place}",
    "{niche} {place} contact",
    "meilleur {niche} {place}",
    "{niche} professionnel {place}",
]
_BROAD_TERMS = [
    "entreprise plomberie suisse romande",
    "société chauffage suisse romande",
    "installateur sanitaire romand",
    "dépannage plomberie urgence",
    "rénovation installations sanitaires",
    "technique du bâtiment plomberie",
    "chauffagiste romandie",
    "artisan plombier romandie",
]


def _all_ddgs_candidates() -> List[Tuple[str, str, str]]:
    """The full combinatorial pool of DDGS query candidates this layer can draw
    from — every (niche, place) pair across every phrasing template, plus broad
    terms with/without a LinkedIn filter. Large enough (thousands of combos) that
    many non-repeating iterations are possible before it's ever exhausted."""
    candidates: List[Tuple[str, str, str]] = []
    all_niches = config.SECONDARY_NICHES + config.PRIMARY_NICHES

    for niche in all_niches:
        for canton in config.TARGET_CANTONS:
            for template in _QUERY_TEMPLATES:
                candidates.append((template.format(niche=niche, place=canton), canton, ""))
            for city in config.CANTON_CITIES.get(canton, []):
                for template in _QUERY_TEMPLATES:
                    candidates.append((template.format(niche=niche, place=city), canton, city))

    for term in _BROAD_TERMS:
        for canton in config.TARGET_CANTONS:
            candidates.append((f"{term} {canton}", canton, ""))
            candidates.append((f"{term} {canton} site:linkedin.com", canton, ""))

    return candidates


def _all_directory_combos() -> List[Tuple[str, str, str]]:
    """The full (niche, canton, city) pool for local.ch — every configured city,
    every niche, not just a fixed subset — so many iterations have room to find
    genuinely new listings instead of re-querying the same first few cities."""
    combos: List[Tuple[str, str, str]] = []
    all_niches = config.SECONDARY_NICHES + config.PRIMARY_NICHES
    for niche in all_niches:
        for canton in config.TARGET_CANTONS:
            for city in config.CANTON_CITIES.get(canton, [canton]):
                combos.append((niche, canton, city))
    return combos


async def _recrawl_ddgs(queries: List[Tuple[str, str, str]], existing_phones: Set[str],
                         existing_names: Set[str], iteration: int) -> List[Dict[str, Any]]:
    new_leads: List[Dict[str, Any]] = []
    start = time.monotonic()
    # Small concurrent batches instead of one query at a time — ddgs_gate's own
    # semaphore/pacing/circuit-breaker still gate every real call identically
    # either way, this just stops the caller from idling between them. Note:
    # existing_phones/existing_names are checked-then-added per query within a
    # batch, so two queries in the SAME batch could in rare cases both slip a
    # duplicate through — main.py's final safety-net dedup catches that.
    batch_size = max(1, config.NET_MAX_CONCURRENT_DDGS)

    async def _one_query(query: str, canton_hint: str, city_hint: str) -> List[Dict[str, Any]]:
        check_cancellation()
        results = await ddgs_gate.search(query, max_results=10)
        found = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            link = r.get("href", "")
            full_text = f"{title} {body}"

            # HARD GATE: same as Layer 1 — no trade keyword = rejected here,
            # never enters the DB or any downstream layer.
            if not is_trade_relevant(full_text):
                continue

            company_name = clean_company_title(title)
            name_key = normalize_name(company_name)
            phones = extract_phones(full_text)
            phone = phones[0] if phones else ""
            normalized_phone = normalize_swiss_phone(phone)
            if not normalized_phone:
                continue

            niche = detect_niche(full_text)
            if not niche:
                continue

            if normalized_phone in existing_phones:
                continue
            if name_key and name_key in existing_names:
                continue
            if is_blacklisted(normalized_phone):
                continue
            if name_key and is_blacklisted_by_name(name_key):
                continue
            existing_phones.add(normalized_phone)
            if name_key:
                existing_names.add(name_key)

            found.append({
                "company_name": company_name,
                "phone": phone,
                "website": link,
                "city": city_hint,
                "canton": canton_hint or detect_canton(full_text),
                "niche": niche,
                "source": f"recrawl_iter{iteration}",
                "raw_snippet": body[:500],
            })
        return found

    for i in range(0, len(queries), batch_size):
        if time.monotonic() - start > _DDGS_LOOP_TIME_BUDGET:
            logger.info(f"DDGS recrawl time budget ({_DDGS_LOOP_TIME_BUDGET}s) reached — "
                        f"moving on with {len(new_leads)} leads found so far.")
            break
        chunk = queries[i:i + batch_size]
        chunk_results = await asyncio.gather(*(_one_query(q, ch, ci) for q, ch, ci in chunk))
        for found in chunk_results:
            new_leads.extend(found)

    return new_leads


async def _recrawl_directory(combos: List[Tuple[str, str, str]], existing_phones: Set[str],
                              existing_names: Set[str], target: int, iteration: int) -> List[Dict[str, Any]]:
    """local.ch directory expansion — independent of DuckDuckGo, so it keeps Layer 4
    productive even when DDGS is fully throttled or blocked."""
    new_leads: List[Dict[str, Any]] = []

    try:
        from utils.search_ch import SearchChClient
    except ImportError:
        return new_leads

    client = SearchChClient(config.SEARCH_CH_API_KEY)
    start = time.monotonic()
    # See layer1_discovery.py's _DIRECTORY_CONCURRENCY — SearchChClient's rate
    # limiter is a shared thread-safe lock, so running several combos "at once"
    # doesn't raise the actual request rate to local.ch, it just keeps those
    # >=2s windows from sitting idle while one result gets parsed.
    concurrency = 6

    async def _one_combo(niche: str, canton: str, city: str) -> List[Dict[str, Any]]:
        check_cancellation()
        try:
            # See layer1_discovery.py's _search_directory for why this timeout must
            # comfortably exceed real batch duration: asyncio.wait_for can't kill the
            # underlying OS thread, so a too-short timeout just discards real results
            # instead of actually saving time.
            results = await asyncio.wait_for(
                asyncio.to_thread(client.search, niche, city, 6), timeout=60
            )
        except Exception as e:
            logger.warning(f"local.ch directory error for {niche} in {city}: {e}")
            return []

        found = []
        for r in results:
            company_name = r.get("name", "")
            name_key = normalize_name(company_name)
            raw_phone = r.get("phone", "")
            phone_key = normalize_swiss_phone(raw_phone) or re.sub(r'\s+', '', raw_phone)

            # For local.ch directory results, the niche is determined by the
            # search query used (already trade-specific). Verify the category
            # field also makes sense — skip results whose category is clearly
            # non-trade (e.g., a restaurant that happened to match a search).
            category = r.get("category", "")
            query_niche = niche
            resolved_niche = detect_niche(category) or detect_niche(query_niche) or query_niche
            if not resolved_niche:
                continue  # genuinely non-trade result
            niche = resolved_niche

            if phone_key and phone_key in existing_phones:
                continue
            if name_key and name_key in existing_names:
                continue
            if phone_key and is_blacklisted(phone_key):
                continue
            if name_key and is_blacklisted_by_name(name_key):
                continue
            if phone_key:
                existing_phones.add(phone_key)
            if name_key:
                existing_names.add(name_key)

            found.append({
                "company_name": company_name,
                "phone": raw_phone,
                "email": r.get("email", ""),
                "website": r.get("website", ""),
                "city": r.get("city", city),
                "postal_code": r.get("postal_code", ""),
                "address": r.get("address", ""),
                "canton": r.get("canton") or canton,
                "niche": niche,
                "source": f"recrawl_directory_iter{iteration}",
                "raw_snippet": r.get("category", ""),
            })
        return found

    try:
        for i in range(0, len(combos), concurrency):
            if len(new_leads) >= target:
                return new_leads
            if time.monotonic() - start > _DIRECTORY_TIME_BUDGET:
                logger.info(f"local.ch recrawl time budget ({_DIRECTORY_TIME_BUDGET}s) reached — "
                            f"moving on with {len(new_leads)} leads found so far.")
                return new_leads

            chunk = combos[i:i + concurrency]
            chunk_results = await asyncio.gather(*(_one_combo(n, c, ci) for n, c, ci in chunk))
            for found in chunk_results:
                new_leads.extend(found)
    finally:
        client.close()

    return new_leads


async def recrawl(existing_leads: List[Dict[str, Any]], iteration: int,
                   used_queries: Set[str], used_combos: Set[Tuple[str, str, str]]) -> List[Dict[str, Any]]:
    """
    Adaptive re-crawl. `used_queries`/`used_combos` are owned by the caller (see
    main.py) and persist across the WHOLE recrawl loop — every call here draws a
    fresh batch excluding anything already tried in an earlier iteration of this
    same run, so many iterations keep finding new territory instead of
    rediscovering the same businesses.
    """
    existing_phones: Set[str] = {l.get("phone", "") for l in existing_leads if l.get("phone")}
    existing_names: Set[str] = {normalize_name(l.get("company_name", "")) for l in existing_leads
                                 if l.get("company_name")}
    existing_names.discard("")

    all_ddgs = _all_ddgs_candidates()
    fresh_ddgs = [q for q in all_ddgs if q[0] not in used_queries]
    random.shuffle(fresh_ddgs)
    queries = fresh_ddgs[:_MAX_QUERIES_PER_ITERATION]
    used_queries.update(q[0] for q in queries)

    all_combos = _all_directory_combos()
    fresh_combos = [c for c in all_combos if c not in used_combos]
    random.shuffle(fresh_combos)
    combos = fresh_combos[:_MAX_DIRECTORY_COMBOS_PER_ITERATION]
    used_combos.update(combos)

    if not queries and not combos:
        console.print("  [yellow]Exhausted all available search combinations for this market.[/yellow]")
        return []

    console.print(f"  Iteration {iteration}: {len(queries)} fresh DuckDuckGo queries "
                  f"({len(used_queries)} tried so far) + {len(combos)} fresh local.ch combos "
                  f"({len(used_combos)} tried so far)")

    ddgs_leads, directory_leads = await asyncio.gather(
        _recrawl_ddgs(queries, existing_phones, existing_names, iteration),
        _recrawl_directory(combos, existing_phones, existing_names, target=60, iteration=iteration),
    )

    new_leads = ddgs_leads + directory_leads
    console.print(f"  → Found {len(new_leads)} new leads in iteration {iteration} "
                  f"(DDGS: {len(ddgs_leads)}, local.ch: {len(directory_leads)})")
    return new_leads
