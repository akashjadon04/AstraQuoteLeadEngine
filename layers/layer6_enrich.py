# ============================================================
# layer6_enrich.py — Contact Enrichment & Validation
# Validates phones, discovers emails, and finds decision-makers.
# Decision-maker lookup tries the lead's OWN website first (scraped
# once already in Layer 5 — reused here, no extra request), then
# SHAB, then name-mining, then a capped DDGS LinkedIn search — but
# unlike a simple first-match waterfall, it keeps going until a
# manager-tier contact (gérant/directeur/responsable — preferred)
# is found or every source is exhausted, always keeping whichever
# candidate found so far ranks highest (manager > owner > other >
# inferred). A lead with no named contact at all can't be cold-called
# credibly, so utils.scoring gates ICP qualification on this.
# All DDGS calls go through the shared rate-limited/circuit-breakered
# gate; all blocking calls (DNS, DDGS, SHAB) are wrapped so a slow
# lookup can never stall the batch.
# ============================================================

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import dns.resolver
import phonenumbers
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn

import config
from utils.database import update_lead
from utils.logger import get_logger
from utils.net import ddgs_gate
from utils.company_size import estimate_company_size
from utils.scoring import CONTACT_TIER_RANK, classify_contact_tier, compute_fit_score
from utils.shab_client import find_officer
from utils.state_manager import check_cancellation

logger = get_logger("layer6")
console = Console()

_TITLE_DISPLAY = {
    "directeur": "Directeur", "directrice": "Directrice", "gérant": "Gérant", "gérante": "Gérante",
    "fondateur": "Fondateur", "fondatrice": "Fondatrice", "propriétaire": "Propriétaire",
    "responsable technique": "Responsable Technique", "associé": "Associé", "associée": "Associée",
    "administrateur": "Administrateur", "ceo": "CEO", "chef d'entreprise": "Chef d'entreprise",
    "patron": "Patron",
}
_NAME_SPAN_RE = re.compile(r"\b([A-ZÀ-Ý][a-zà-ÿ'’\-]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ'’\-]+){1,2})\b")
_NAME_STOPWORDS = {
    "directeur", "directrice", "général", "générale", "gérant", "gérante", "fondateur", "fondatrice",
    "propriétaire", "responsable", "technique", "associé", "associée", "administrateur", "ceo",
    "chef", "entreprise", "patron", "monsieur", "madame", "sàrl", "sarl", "genève", "vaud", "fribourg",
    "valais", "neuchâtel", "jura", "suisse", "route", "rue", "avenue", "chemin",
}

# Many Swiss trade businesses carry their owner's name inside the company name
# itself — either fully ("Portier Eric SA", "Zampilli Salvatore"), embedded next
# to trade words ("Sanitaire Garin Marcel", "Philippe Andrey Installations
# Sanitaires SA"), as a bare family name ("Dalloyeau Sàrl", "Mooser SA"), or as a
# founding partnership ("Décotterd & Bulliard Sàrl"). Mining that is free,
# instant, and works even when every network source is down. Guarded by
# stop-lists (trade terms, places, marketing words) so brand names like
# "Speedy-canalisations" or "Léman Fluides" never get mistaken for people.
_TRADE_DESCRIPTOR_WORDS = {
    "plombier", "plombiers", "plomberie", "sanitaire", "sanitaires", "chauffage", "chauffages",
    "chauffagiste", "hvac", "climatisation", "clima", "installation", "installations",
    "depannage", "dépannage", "depannages", "dépannages", "service", "services", "entreprise",
    "construction", "renovation", "rénovation", "energie", "énergie", "energies", "énergies",
    "technique", "techniques", "haustechnik", "wärmetechnik", "group", "groupe", "ferblanterie",
    "ferblantier", "couverture", "couvreur", "couvreurs", "etancheite", "étanchéité", "solutions",
    "systemes", "systèmes", "maintenance", "urgence", "canalisations", "debouchage", "débouchage",
    "toiture", "toitures", "multiservices", "isolation", "ventilation", "climat", "fluide",
    "fluides", "eau", "eaux", "electricien", "électricien", "electriciens", "électriciens",
    # Adjacent trades added to widen the addressable market — see
    # config.SECONDARY_NICHES. Without these, a company name like "Maçon Dupont
    # Sàrl" or "Menuisier Général SA" would let the trade word itself get mined
    # as a candidate first/last name (the exact class of bug already fixed for
    # "couvreur" — see the reconciliation notes above).
    "menuisier", "menuisiers", "menuiserie", "peintre", "peintres", "peinture",
    "maçon", "macon", "maçons", "macons", "maçonnerie", "maconnerie", "carreleur",
    "carreleurs", "carrelage", "carrelages", "serrurier", "serruriers", "serrurerie",
    "vitrier", "vitriers", "vitrerie", "générale", "generale", "bâtiment", "batiment",
    # Found live in delivered leads: generic/product words the mining logic was
    # accepting as a "surname" because nothing stopped them — "BK Verre SA" (SA
    # literally means glass) produced the contact name "Verre", and "Société
    # Electrique du Val-de-Travers SA" produced "Société" (Company). Same root
    # cause as the couvreur/électricien gaps above, different words.
    "société", "societe", "sociétés", "societes", "métal", "metal", "métaux",
    "metaux", "verre", "verres", "glass", "stores", "travaux", "agencement",
    "agencements", "revêtement", "revetement", "revêtements", "revetements",
    "paysagiste", "paysagistes", "elektro", "paroisse", "paroisses",
    # "électricien" (the profession) was already covered, but "électricité"
    # (the general noun, "electricity") is a different word and slipped
    # through in "Barras Electricité Partners SA" -> fake "Barras Electricité
    # Partners". "Partners"/"Romandie" (Etavis Romandie SA -> fake "Etavis
    # Romandie") are the same class of gap: generic business/region words
    # that read as capitalized "names" but aren't a person.
    "électricité", "electricite", "electricités", "electricites",
    "partners", "partner", "romandie",
}
_CONNECTOR_WORDS = {
    "et", "de", "du", "des", "la", "le", "les", "fils", "cie", "sa", "sàrl", "sarl", "sagl",
    "ag", "gmbh", "snc", "succ", "successeur", "titulaire", "frères", "freres", "associés",
    "associes", "père", "pere",
}
_MARKETING_WORDS = {
    "speedy", "pro", "express", "rapide", "plus", "concept", "confort", "innovation",
    "digital", "swiss", "suisse", "romand", "romande", "général", "générale", "general",
    "atelier", "centre", "center", "eco", "alpine", "léman", "leman", "rhône", "rhone",
    "riviera", "chablais", "gratuit", "garanti", "téléphone", "telephone", "devis",
    # German names of configured towns (config lists the French ones)
    "murten", "düdingen", "dudingen", "freiburg", "genf", "wallis", "sitten",
    # Region/locality names seen live mistaken for a person's surname because
    # they aren't among the ~8-10 curated cities per canton in
    # config.CANTON_CITIES (Switzerland has thousands of localities — this
    # list can never be exhaustive, so the _AREA_DESCRIPTION_MARKERS bail-out
    # below is the more general backstop for names this specific list misses).
    "vallorbe", "côte", "cote", "vaudoise", "vaudois", "sainte-croix",
    # "Arc Jura(ssien)" is a real regional-branding term ("Marti Arc Jura SA"
    # produced the fake surname "Marti Arc" once "Jura" the canton was
    # stripped) — bare enough to also risk false positives elsewhere, but a
    # real person surnamed exactly "Arc" is vanishingly rare in this dataset.
    "arc",
}
# If a company name contains one of these, it's describing a SERVICE AREA
# ("Sanitaire proche Yverdon, Vallorbe, Sainte-Croix" = "Sanitary [services] near
# X, Y, Z"), not naming a specific business — mining a "surname" out of whatever
# capitalized words are left (a village name, most often) is worse than no name
# at all. Bail out of mining entirely rather than guess.
_AREA_DESCRIPTION_MARKERS = re.compile(
    r"\b(proche|r[ée]gion|secteur|environs|alentours|autour\s+de)\b", re.IGNORECASE
)
# Substrings that mark a single word as a trade brand rather than a family name
# ("Imerisan", "Vivatec", "Sanichauffe"...). Only applied to bare-surname guesses,
# where a wrong guess is likeliest.
_TRADE_FRAGMENTS = ("san", "therm", "clim", "chauff", "tech", "tec", "energ", "aqua",
                     "hydro", "canal", "toit", "ferbl", "renov", "install", "plomb",
                     "elec", "solar", "vent", "isol")
_PARTNERSHIP_RE = re.compile(r"^([A-ZÀ-Ý][\w'’\-]+)\s+(?:&|et)\s+([A-ZÀ-Ý][\w'’\-]+)")
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z.&'’\-]{0,3}$")

_TITLE_FULL_GUESS = "Propriétaire probable (déduit du nom de l'entreprise)"
_TITLE_SURNAME_GUESS = "Propriétaire probable — nom de famille (déduit du nom de l'entreprise)"
_TITLE_PARTNER_GUESS = "Associés fondateurs probables (déduit du nom de l'entreprise)"


def _validate_phone(phone: str) -> dict:
    """Validate phone and detect type. Formats E.164 (e.g. '+41227367265'), matching
    Layer 2 exactly — this value doubles as the database upsert key (utils.database
    upserts ON CONFLICT(phone)), so it must stay byte-identical to what Layer 2 already
    wrote, or every update_lead() call in this layer silently matches zero rows."""
    result = {"valid": False, "formatted": None, "is_mobile": False}
    if not phone:
        return result
    try:
        parsed = phonenumbers.parse(phone, "CH")
        if phonenumbers.is_valid_number(parsed):
            result["valid"] = True
            result["formatted"] = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
            num_type = phonenumbers.number_type(parsed)
            result["is_mobile"] = num_type == phonenumbers.PhoneNumberType.MOBILE
    except phonenumbers.NumberParseException:
        pass
    return result


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return ""
    url = url.replace("https://", "").replace("http://", "")
    return url.split("/")[0].split("?")[0]


def _resolve_domain_sync(domain: str) -> bool:
    """Blocking DNS check — always called via asyncio.to_thread, with tight bounds."""
    resolver = dns.resolver.Resolver()
    resolver.timeout = 3
    resolver.lifetime = 5
    for record_type in ("MX", "A"):
        try:
            resolver.resolve(domain, record_type)
            return True
        except Exception:
            continue
    return False


async def _discover_email(lead: dict) -> Optional[str]:
    """Try to discover an email from the website domain (MX/A record presence)."""
    domain = _extract_domain(lead.get("website", ""))
    if not domain or "." not in domain:
        return None

    skip_domains = ["duckduckgo.com", "google.com", "local.ch", "search.ch",
                     "facebook.com", "instagram.com", "linkedin.com"]
    if any(d in domain for d in skip_domains):
        return None

    ok = await asyncio.to_thread(_resolve_domain_sync, domain)
    return f"info@{domain}" if ok else None


def _extract_decision_maker(candidates: List[str]) -> Dict[str, Optional[str]]:
    """Best-effort name extraction from text lines Layer 5 flagged as containing a
    decision-maker title (scraped from the lead's own about/team/impressum page).
    A page can mention more than one person (e.g. a founder AND an operations
    manager) — when it does, prefer whichever candidate reads as the highest
    contact tier (manager > owner > other) rather than just the first
    title-bearing line encountered."""
    best: Dict[str, Optional[str]] = {"name": None, "title": None}
    best_rank = -1
    for line in candidates:
        line_lower = line.lower()
        matched_kw = next((kw for kw in _TITLE_DISPLAY if kw in line_lower), None)
        if not matched_kw:
            continue

        for span in _NAME_SPAN_RE.findall(line):
            words = span.lower().split()
            if any(w in _NAME_STOPWORDS for w in words):
                continue
            title = _TITLE_DISPLAY[matched_kw]
            rank = CONTACT_TIER_RANK[classify_contact_tier({"decision_maker": span, "decision_title": title})]
            if rank > best_rank:
                best, best_rank = {"name": span, "title": title}, rank
            break

    return best


def _place_words() -> set:
    """All configured city/canton words, lowercased, so 'Bianco SA Sion' doesn't
    keep 'Sion' as part of a person name."""
    words = set()
    for canton, cities in config.CANTON_CITIES.items():
        words.add(canton.lower())
        for city in cities:
            words.update(part.lower() for part in re.split(r"[\s\-]+", city))
    return words


_PLACE_WORDS = _place_words()


def _mine_owner_from_company_name(company_name: str, lead_city: str = "", lead_canton: str = "") -> Optional[Dict[str, str]]:
    """Extract a probable owner name from the company name itself.
    Returns {'name', 'title'} with a clearly-labeled inferred title, or None.

    lead_city/lead_canton: this SPECIFIC lead's own location — always accurate
    for this lead even when the town isn't one of the ~8-10 curated per canton
    in config.CANTON_CITIES ("Piémontesi Savagnier SA" produced the fake
    surname "Savagnier" because Savagnier isn't in that curated list — but the
    lead's own `city` field already says "Savagnier", so it's known here
    regardless of whether the global curated list happens to include it)."""
    if not company_name:
        return None

    # A service-area description ("Sanitaire proche Yverdon, Vallorbe...") is
    # not a business identity — whatever capitalized tokens survive the stop-
    # lists below would most likely be an un-listed village name, not a
    # person. Refuse to guess rather than mine a village name as a "surname".
    if _AREA_DESCRIPTION_MARKERS.search(company_name):
        return None

    lead_place_words = {w.lower() for w in re.split(r"[\s\-]+", f"{lead_city} {lead_canton}") if w}

    # Founding partnership: "Décotterd & Bulliard", "Dupasquier et Ruga".
    partner_match = _PARTNERSHIP_RE.match(company_name.strip())
    if partner_match:
        left, right = partner_match.group(1), partner_match.group(2)
        stops = _TRADE_DESCRIPTOR_WORDS | _MARKETING_WORDS | _PLACE_WORDS | _CONNECTOR_WORDS | lead_place_words
        if (left.lower() not in stops and right.lower() not in stops
                and not any(f in left.lower() for f in _TRADE_FRAGMENTS)
                and not any(f in right.lower() for f in _TRADE_FRAGMENTS)):
            return {"name": f"{left} & {right}", "title": _TITLE_PARTNER_GUESS}

    # "titulaire X" in the registered name explicitly names the owner.
    titulaire_match = re.search(r"titulaire\s+([A-ZÀ-Ý][\w'’\-]+)", company_name)
    if titulaire_match:
        return {"name": titulaire_match.group(1), "title": _TITLE_SURNAME_GUESS}

    # General token cleanup: drop legal/connector/trade/marketing/place words and
    # acronyms; keep what looks like person-name tokens, preserving order.
    stops = _TRADE_DESCRIPTOR_WORDS | _CONNECTOR_WORDS | _MARKETING_WORDS | _PLACE_WORDS | lead_place_words
    kept: List[str] = []
    for raw in re.split(r"[\s,]+", company_name):
        token = raw.strip(".-–'’&")
        if not token or any(ch.isdigit() for ch in token):
            continue
        if _ACRONYM_RE.match(token):
            continue
        if token.isupper() and len(token) >= 5:
            token = token.title()
        if not token[0].isupper():
            continue
        # Article contractions ("L'Art", "D'eau") are phrases, not surnames.
        if re.match(r"^[A-Za-zÀ-ÿ]'", token):
            continue
        low = token.lower()
        if low in stops:
            continue
        # Hyphenated compounds of stop-words ("Sanitaire-Chauffage") are trade
        # terms too; hyphenated surnames ("Humbert-Droz") pass because their
        # parts aren't in the stop-lists.
        if "-" in token and all(part in stops for part in low.split("-") if part):
            continue
        if not re.fullmatch(r"[A-ZÀ-Ý][\wà-ÿ'’\-]+", token):
            continue
        if low not in (k.lower() for k in kept):
            kept.append(token)

    # Brand-fragment guard, tiered by evidence strength: a 2-3 word all-caps-free
    # name is strong evidence of a person, so tolerate one fragment-y token there
    # ("Vieira Dos Santos" keeps its 'San'); a bare single token is weak evidence,
    # so any fragment kills it ("Imerisan", "Sani-Dep").
    clean = [t for t in kept if not any(f in t.lower() for f in _TRADE_FRAGMENTS)]

    if len(kept) in (2, 3) and len(clean) >= len(kept) - (1 if len(kept) == 3 else 0):
        return {"name": " ".join(kept), "title": _TITLE_FULL_GUESS}

    if len(clean) == 1 and len(clean[0]) >= 4:
        return {"name": clean[0], "title": _TITLE_SURNAME_GUESS}

    return None


_COMPANY_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)


def _company_mentioned(company_name: str, text: str) -> bool:
    """Require a distinctive word from the company name to actually appear in the
    search result text before trusting a DDGS match. Verified necessary live: DDGS
    can return completely unrelated LinkedIn profiles (e.g. searching a Swiss
    plumbing company returned random people in Algeria) rather than an empty
    result when it has nothing relevant — accepting the first linkedin.com/in/ hit
    unconditionally would attach a stranger's name to this lead, which is worse
    for a cold-calling list than having no name at all."""
    company_words = {w.lower() for w in _COMPANY_WORD_RE.findall(company_name) if len(w) > 3}
    if not company_words:
        return False
    text_lower = text.lower()
    return any(w in text_lower for w in company_words)


def _personalize_opening(opening: str, dm_name: str, dm_title: str, tier: str = "other") -> str:
    """Weave the decision-maker's name into the cold-call opening line. For
    surname-only guesses, use 'M./Mme {surname}' since gender is unknown. For a
    manager/owner-tier contact (a confirmed title, not a name-mining guess),
    also state the role out loud — the rep should know who they're asking for
    AND why that person is the right one, not just a bare name."""
    if not opening or not dm_name:
        return opening
    if "je cherche à joindre" in opening:
        return opening  # already personalized
    display = dm_name
    title_lower = (dm_title or "").lower()
    if "nom de famille" in title_lower:
        display = f"M./Mme {dm_name}"
    role_suffix = ""
    if tier in ("manager", "owner") and dm_title:
        clean_title = re.sub(r"\s*\(.*?\)\s*", "", dm_title).strip()
        if clean_title:
            role_suffix = f", {clean_title.lower()},"
    rest = re.sub(r"^Bonjour\s*,?\s*", "", opening)
    if rest:
        rest = rest[0].upper() + rest[1:]
    return f"Bonjour, je cherche à joindre {display}{role_suffix} {rest}"


_DASH_SPLIT_RE = re.compile(r"\s[-–—]\s")
_CLEAN_NAME_RE = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ'’.\-]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ'’.\-]+){1,3}$")


def _clean_ddgs_name(title: str) -> Optional[str]:
    """DDGS LinkedIn result titles are messy and inconsistently formatted — split
    on any dash variant (a plain '-' split alone missed real results using an
    en-dash, which silently stored the ENTIRE raw title — including the trailing
    '| LinkedIn' and, seen live, other concatenated results — as the "name").
    Only return something that actually looks like a clean 2-4 word person name;
    anything else is rejected rather than stored, since garbage here is worse
    than no name at all for a cold-calling list."""
    candidate = _DASH_SPLIT_RE.split(title, maxsplit=1)[0]
    candidate = re.split(r"\s*\|", candidate)[0].strip()
    if _CLEAN_NAME_RE.match(candidate):
        return candidate
    return None


async def _find_decision_maker_ddgs(company_name: str) -> dict:
    """Fallback: search for a decision-maker on LinkedIn via DuckDuckGo (capped, rate-limited)."""
    result: Dict[str, Optional[str]] = {"name": None, "title": None, "linkedin": None}
    if not config.ENABLE_DM_SEARCH_FALLBACK or not company_name:
        return result

    results = await ddgs_gate.search(
        f'"{company_name}" directeur OR gérant OR responsable site:linkedin.com', max_results=5
    )
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        url = r.get("href", "")
        if "linkedin.com/in/" not in url:
            continue
        if not _company_mentioned(company_name, f"{title} {body}"):
            continue
        name = _clean_ddgs_name(title)
        if not name:
            continue  # this result's title didn't parse into a clean name — try the next one
        parts = _DASH_SPLIT_RE.split(title, maxsplit=1)
        role = re.split(r"\s*\|", parts[1])[0].strip() if len(parts) > 1 else ""
        result["name"] = name
        result["title"] = role
        result["linkedin"] = url
        break

    return result


async def _enrich_lead_inner(lead: Dict[str, Any]) -> Dict[str, Any]:
    score = 0

    # 1. Phone validation (required — leads without a verified number are disqualified)
    phone_result = _validate_phone(lead.get("phone", ""))
    if phone_result["valid"]:
        lead["phone"] = phone_result["formatted"]
        lead["is_mobile"] = phone_result["is_mobile"]
        score += 30
    else:
        lead["disqualified"] = True
        lead["disqualification_reason"] = "No verified phone number"
        lead["contact_score"] = 0
        return lead

    # 2. Email discovery
    if not lead.get("email"):
        lead["email"] = await _discover_email(lead)
    if lead.get("email"):
        score += 20

    # 3. Decision-maker. Tries sources in decreasing order of authority — (a) the
    #    company's own team/about page, scraped once in Layer 5 and reused; (b)
    #    SHAB, the official gazette where every registered officer appointment is
    #    legally published; (c) mining the company name itself (Swiss trade
    #    businesses are very often named after their owner); (d) a DDGS LinkedIn
    #    search, last resort, only accepted when the result verifiably mentions
    #    this company — but does NOT stop at the first source that finds any
    #    name. It keeps going until a manager-tier contact (gérant/directeur/
    #    responsable) is found or every source has been tried, always keeping
    #    the best-ranked candidate seen so far (manager > owner > other >
    #    inferred). Outreach on a name nobody can vouch for the role of is worse
    #    than outreach on the RIGHT person, so this is deliberately thorough
    #    rather than fast.
    if not lead.get("decision_maker"):
        best_dm: Dict[str, Optional[str]] = {"name": None, "title": None}
        best_rank = -1

        def _consider(candidate: Optional[Dict[str, Optional[str]]]) -> None:
            nonlocal best_dm, best_rank
            if not candidate or not candidate.get("name"):
                return
            rank = CONTACT_TIER_RANK[classify_contact_tier(
                {"decision_maker": candidate["name"], "decision_title": candidate.get("title") or ""}
            )]
            if rank > best_rank:
                best_dm, best_rank = candidate, rank

        _consider(_extract_decision_maker(lead.get("_dm_candidates", [])))

        if best_rank < CONTACT_TIER_RANK["manager"] and config.ENABLE_SHAB_LOOKUP:
            try:
                shab_officer = await asyncio.wait_for(
                    asyncio.to_thread(find_officer, lead.get("company_name", ""),
                                       lead.get("zefix_uid", "") or ""),
                    timeout=25,
                )
            except asyncio.TimeoutError:
                shab_officer = None
            if shab_officer:
                # officer_count is a registry-grade size signal (see company_size).
                if shab_officer.get("officer_count"):
                    lead["officer_count"] = shab_officer["officer_count"]
                _consider({"name": shab_officer["name"],
                           "title": f"{shab_officer['title']} (registre officiel SHAB)"})

        if best_rank < 0:
            # Mining can only ever produce an 'inferred' guess — not worth trying
            # if a stronger source already found something.
            mined = _mine_owner_from_company_name(
                lead.get("company_name", ""), lead.get("city", ""), lead.get("canton", "")
            )
            _consider(mined)

        if best_rank < CONTACT_TIER_RANK["owner"]:
            # Own short timeout — the shared ddgs_gate has limited concurrency, so
            # under load this shouldn't be allowed to eat the whole per-lead budget.
            try:
                ddgs_dm = await asyncio.wait_for(
                    _find_decision_maker_ddgs(lead.get("company_name", "")), timeout=8
                )
            except asyncio.TimeoutError:
                ddgs_dm = {"name": None, "title": None, "linkedin": None}
            if ddgs_dm.get("name"):
                _consider(ddgs_dm)
                if best_dm is ddgs_dm and ddgs_dm.get("linkedin"):
                    lead["decision_maker_linkedin"] = ddgs_dm["linkedin"]

        if best_dm["name"]:
            lead["decision_maker"] = best_dm["name"]
            lead["decision_title"] = best_dm["title"]
            tier = classify_contact_tier(lead)
            lead["custom_opening"] = _personalize_opening(
                lead.get("custom_opening", ""), best_dm["name"], best_dm["title"], tier
            )
            score += 30

    # 4. Address
    if lead.get("address"):
        score += 20

    # 5. Website & social
    domain = _extract_domain(lead.get("website", ""))
    if domain and not any(d in domain for d in ["duckduckgo", "google", "local.ch"]):
        score += 10
    if lead.get("has_instagram") or lead.get("has_facebook") or lead.get("has_linkedin"):
        score += 10

    lead["contact_score"] = min(score, 100)
    lead["status"] = "enriched"
    lead["layer_reached"] = 6

    # Company-size estimate — must run BEFORE the fit score, which now weights
    # size off the estimated band (see utils/company_size.py + utils/scoring.py).
    # This is what stops one/two-person shops from scoring like real firms.
    size = estimate_company_size(lead)
    lead["size_band"] = size["band"]
    lead["employees_estimate"] = size["employees_estimate"]
    lead["size_signals"] = json.dumps(size["signals"], ensure_ascii=False)

    # ICP fit score — computed last since it uses everything gathered by Layers
    # 5 and 6 (company-size band, legal form, Zefix status, digital signals,
    # niche, decision-maker). Distinct from contact_score above: that measures
    # how COMPLETE this lead's data is, this measures how well the BUSINESS
    # matches who actually buys and uses AstraQuote.
    fit = compute_fit_score(lead)
    lead["fit_score"] = fit["score"]
    lead["fit_score_breakdown"] = json.dumps(fit["breakdown"], ensure_ascii=False)

    if lead.get("phone"):
        updates = {
            "email": lead.get("email"),
            "decision_maker": lead.get("decision_maker"),
            "decision_title": lead.get("decision_title"),
            "decision_maker_linkedin": lead.get("decision_maker_linkedin"),
            "contact_score": lead["contact_score"],
            "is_mobile": lead.get("is_mobile", False),
            "size_band": lead["size_band"],
            "employees_estimate": lead["employees_estimate"],
            "size_signals": lead["size_signals"],
            "officer_count": lead.get("officer_count"),
            "team_headcount_hint": lead.get("team_headcount_hint"),
            "fit_score": lead["fit_score"],
            "fit_score_breakdown": lead["fit_score_breakdown"],
            "status": "enriched",
            "layer_reached": 6,
        }
        # Only persist the opening when we actually have one — never overwrite
        # Layer 5's stored opening with NULL if this dict came in without it.
        if lead.get("custom_opening"):
            updates["custom_opening"] = lead["custom_opening"]
        update_lead(lead["phone"], updates)

    return lead


async def enrich_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single lead with validated contact information. Hard-capped at
    config.LEAD_ENRICH_TIMEOUT so a slow lookup can never stall the batch."""
    try:
        return await asyncio.wait_for(_enrich_lead_inner(lead), timeout=config.LEAD_ENRICH_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"Enrichment timed out for {lead.get('company_name', 'Unknown')} — keeping partial results.")
    except Exception as e:
        logger.error(f"Enrichment crashed for {lead.get('company_name', 'Unknown')}: {e}")

    lead.setdefault("contact_score", 30 if lead.get("phone") else 0)
    lead["status"] = "enriched"
    lead["layer_reached"] = 6
    if "fit_score" not in lead:
        size = estimate_company_size(lead)
        lead["size_band"] = size["band"]
        lead["employees_estimate"] = size["employees_estimate"]
        lead["size_signals"] = json.dumps(size["signals"], ensure_ascii=False)
        fit = compute_fit_score(lead)
        lead["fit_score"] = fit["score"]
        lead["fit_score_breakdown"] = json.dumps(fit["breakdown"], ensure_ascii=False)
        if lead.get("phone"):
            update_lead(lead["phone"], {
                "size_band": lead["size_band"],
                "employees_estimate": lead["employees_estimate"],
                "size_signals": lead["size_signals"],
                "fit_score": lead["fit_score"],
                "fit_score_breakdown": lead["fit_score_breakdown"],
            })
    return lead


async def batch_enrich(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enrich all leads with contact validation and enrichment."""
    semaphore = asyncio.Semaphore(config.ENRICH_CONCURRENCY)

    with Progress(TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TextColumn("{task.completed}/{task.total}")) as progress:
        task = progress.add_task("Enriching contacts...", total=len(leads))

        async def process_enrich(i, lead):
            async with semaphore:
                check_cancellation()
                company = lead.get("company_name", "Unknown")
                result = await enrich_lead(lead)

                if result.get("disqualified"):
                    console.print(f"  [red]✗[/red] {company} — disqualified (no phone)")
                else:
                    console.print(
                        f"  [green]✓[/green] {company} — "
                        f"Contact: {result['contact_score']}% | "
                        f"Email: {'✓' if result.get('email') else '✗'} | "
                        f"DM: {'✓' if result.get('decision_maker') else '✗'}"
                    )

                progress.advance(task)
                return result

        tasks = [process_enrich(i, lead) for i, lead in enumerate(leads)]
        results = await asyncio.gather(*tasks)
        enriched = [r for r in results if not r.get("disqualified")]

    return enriched
