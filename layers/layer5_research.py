# ============================================================
# layer5_research.py — Deep Research & Public-Info Analysis
# Rule-based research agent: NO external AI/LLM. Every signal
# (digital maturity, pain points, urgency, pitch angle, opening
# line) is derived deterministically from publicly observable
# data — the lead's own website, its structured contact data,
# and (optionally, capped) Google reviews and social presence.
# ============================================================

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn

import config
from utils.database import update_lead
from utils.logger import get_logger
from utils.net import ddgs_gate
from utils.state_manager import check_cancellation, update_state
from utils.web_analyzer import analyze_website
from utils.zefix_client import lookup_company as zefix_lookup

logger = get_logger("layer5")
console = Console()

_LEGAL_FORM_PATTERNS = [
    (re.compile(r"\bS\.?à\.?r\.?l\.?\b\.?", re.IGNORECASE), "Sàrl (société à responsabilité limitée)"),
    (re.compile(r"\bSarl\b\.?", re.IGNORECASE), "Sàrl (société à responsabilité limitée)"),
    (re.compile(r"\bSagl\b\.?", re.IGNORECASE), "Sagl"),
    (re.compile(r"\bGmbH\b\.?", re.IGNORECASE), "GmbH"),
    (re.compile(r"\bSA\b\.?", re.IGNORECASE), "SA (société anonyme)"),
    (re.compile(r"\bAG\b\.?", re.IGNORECASE), "AG (Aktiengesellschaft)"),
    (re.compile(r"\bSNC\b\.?", re.IGNORECASE), "SNC (société en nom collectif)"),
]


def _extract_legal_form(company_name: str) -> str:
    """Free, instant, no-network signal: Swiss legal form abbreviations appear
    verbatim in company names, so this is high-confidence whenever a suffix is
    present. No suffix at all usually means an unregistered sole proprietorship."""
    for pattern, label in _LEGAL_FORM_PATTERNS:
        if pattern.search(company_name or ""):
            return label
    return "Raison individuelle (probable)"


_PAIN_REVIEW_PHRASES = [
    "trop lent", "longue attente", "long délai", "jamais rappelé", "jamais recontacté",
    "pas de réponse", "aucune réponse", "sans réponse", "pas rappelé", "trop cher",
]

_NICHE_LABELS = {
    "plomberie": "plombiers",
    "chauffage": "chauffagistes",
    "climatisation": "spécialistes en climatisation",
    "sanitaire": "installateurs sanitaires",
    "ferblanterie": "ferblantiers",
    "installation": "installateurs",
}

_PITCH_TEMPLATES = {
    "no_website": (
        "{company} n'a pas de site internet trouvable, donc tout le chiffrage se fait aujourd'hui à "
        "la main — téléphone, calcul sur place ou tableur le soir. Montrer comment AstraQuote permet "
        "à l'équipe de générer un devis précis en moins de 5 minutes depuis le chantier, sans aucun "
        "rapport avec le fait d'avoir ou non un site web : c'est un outil interne, pas une vitrine."
    ),
    "no_quote_form": (
        "Le site de {company} ne permet pas de démarrer un devis en ligne, ce qui suggère que le "
        "chiffrage se fait encore à la main en interne. Montrer comment AstraQuote remplace ce calcul "
        "manuel par un devis structuré généré par l'équipe en quelques minutes, avec un catalogue "
        "fournisseur intégré et un suivi jusqu'à la facture."
    ),
    "outdated_site": (
        "Le site de {company} est daté — ce qui n'a aucune incidence sur AstraQuote, un outil utilisé "
        "en interne par l'équipe, pas par leurs clients. Montrer le gain de temps sur le chiffrage et "
        "le suivi des devis, indépendamment de l'état du site web."
    ),
    "no_social": (
        "{company} n'a pas de présence détectée sur les réseaux sociaux — sans incidence sur "
        "AstraQuote, qui sert à chiffrer plus vite en interne, pas à la visibilité digitale de "
        "l'entreprise. Montrer le gain de temps sur la rédaction des devis et le suivi jusqu'à la facture."
    ),
    "default": (
        "Présenter comment AstraQuote permet à l'équipe de {company} de générer un devis précis de "
        "plomberie/chauffage en moins de 5 minutes, directement sur le chantier, avec un catalogue "
        "fournisseur intégré et un suivi du devis jusqu'à la facture — et libère le temps administratif "
        "du gérant."
    ),
}

_OPENING_TEMPLATES = {
    "no_website": (
        "Bonjour, j'ai cherché {company} en ligne et je n'ai pas trouvé de site — j'imagine que vos "
        "devis se font encore à la main, par téléphone ou sur place. C'est exactement ce qu'AstraQuote "
        "automatise pour l'équipe, pas besoin d'un site pour ça. Est-ce un sujet qui vous intéresse ?"
    ),
    "no_quote_form": (
        "Bonjour, j'ai vu {company}{city_suffix} — pas de moyen de démarrer un devis en ligne sur votre "
        "site, ce qui laisse penser que le chiffrage se fait encore à la main en interne. Avez-vous "
        "déjà pensé à automatiser cette étape pour votre équipe ?"
    ),
    "outdated_site": (
        "Bonjour, je me permets de vous contacter au sujet de {company}. Je ne vous appelle pas au "
        "sujet de votre site internet, mais de la façon dont votre équipe chiffre ses devis "
        "aujourd'hui — verriez-vous un intérêt à en discuter ?"
    ),
    "no_social": (
        "Bonjour, je vous contacte au sujet de {company}. Nous aidons des équipes {niche_label} à "
        "diviser par 4 le temps passé sur la rédaction de leurs devis, indépendamment de leur présence "
        "en ligne. Seriez-vous ouvert à en discuter ?"
    ),
    "default": (
        "Bonjour, je vous contacte au sujet de {company}{city_suffix} — nous aidons les {niche_label} "
        "romands à diviser par 4 le temps passé sur la rédaction de leurs devis. Seriez-vous ouvert à "
        "en discuter ?"
    ),
}


def _empty_web_data() -> Dict[str, Any]:
    return {
        "has_ssl": False, "has_quote_form": False, "has_booking_system": False,
        "meta_description": "", "has_viewport": False, "contact_emails": [],
        "social_links": {}, "tech_stack": [], "last_copyright_year": None,
        "decision_maker_candidates": [], "team_headcount_hint": None,
        "mentions_team": False, "pages_crawled": 0, "word_count": 0,
        "reachable": False,
    }


def _niche_label(niche: str) -> str:
    return _NICHE_LABELS.get(niche, "artisans")


def _compute_digital_maturity(web_data: Dict[str, Any], social: Dict[str, Optional[str]]) -> int:
    score = 1  # baseline: has a phone number, that's the floor
    if web_data.get("reachable"):
        score += 1
    if web_data.get("has_ssl"):
        score += 1
    if web_data.get("has_quote_form") or web_data.get("has_booking_system"):
        score += 1
    if any(social.values()):
        score += 1
    current_year = datetime.now().year
    is_modern = (
        web_data.get("has_viewport")
        and bool(web_data.get("meta_description"))
        and web_data.get("pages_crawled", 0) >= 2
        and (web_data.get("last_copyright_year") is None or web_data["last_copyright_year"] >= current_year - 3)
    )
    if is_modern:
        score += 1
    return max(1, min(score, 5))


def _dominant_pain_category(web_data: Dict[str, Any]) -> str:
    """The single biggest gap, used to pick a coherent pitch/opening pair."""
    current_year = datetime.now().year
    if not web_data.get("reachable"):
        return "no_website"
    if not web_data.get("has_quote_form") and not web_data.get("has_booking_system"):
        return "no_quote_form"
    stale = web_data.get("last_copyright_year") and web_data["last_copyright_year"] < current_year - 4
    if not web_data.get("has_ssl") or stale:
        return "outdated_site"
    if not web_data.get("social_links"):
        return "no_social"
    return "default"


def _compute_pain_points(lead: Dict[str, Any], web_data: Dict[str, Any], reviews: Dict[str, Any]) -> List[str]:
    points: List[str] = []
    current_year = datetime.now().year

    if not web_data.get("reachable"):
        points.append("Aucun site internet fonctionnel détecté — visibilité en ligne quasi nulle.")
    else:
        if not web_data.get("has_quote_form") and not web_data.get("has_booking_system"):
            points.append("Aucun formulaire de demande de devis en ligne — chaque demande passe par téléphone.")
        if not web_data.get("has_ssl"):
            points.append("Site sans certificat SSL (non sécurisé) — mauvaise image et pénalité SEO.")
        if not web_data.get("has_viewport"):
            points.append("Site non optimisé pour mobile — mauvaise expérience pour la majorité des visiteurs.")
        year = web_data.get("last_copyright_year")
        if year and year < current_year - 4:
            points.append(f"Site visiblement pas mis à jour depuis {year} — image vieillissante.")
        if not web_data.get("contact_emails") and not lead.get("email"):
            points.append("Aucune adresse email publique trouvée — canal de contact limité au téléphone.")

    if not any(web_data.get("social_links", {}).values() if isinstance(web_data.get("social_links"), dict) else []):
        if not lead.get("has_instagram") and not lead.get("has_facebook") and not lead.get("has_linkedin"):
            points.append("Aucune présence sur les réseaux sociaux détectée — faible visibilité digitale.")

    if reviews.get("pain_signals"):
        points.append("Avis clients publics mentionnant des délais de réponse ou de devis lents.")

    if not points:
        points.append("Présence digitale déjà solide — argumentaire à orienter sur le gain de temps et le taux de conversion.")

    return points[:5]


def _compute_urgency(web_data: Dict[str, Any], digital_maturity: int, reviews: Dict[str, Any]) -> int:
    score = (5 - digital_maturity) * 2  # 1 -> 8, 5 -> 0
    if not web_data.get("has_quote_form") and not web_data.get("has_booking_system"):
        score += 1
    if not web_data.get("has_ssl"):
        score += 1
    if reviews.get("pain_signals"):
        score += 1
    if not web_data.get("reachable"):
        score += 1
    return max(1, min(score, 10))


def _estimate_quotes(lead: Dict[str, Any]) -> int:
    employees = lead.get("employee_count")
    if employees:
        try:
            return max(50, int(employees) * 15)
        except (TypeError, ValueError):
            pass
    return 300


async def _find_reviews(company: str, city: str) -> Dict[str, Any]:
    """Best-effort public review lookup — capped, circuit-breaker protected, never blocks the batch."""
    reviews: Dict[str, Any] = {"rating": None, "review_count": 0, "pain_signals": []}
    if not config.ENABLE_REVIEW_SEARCH or not company:
        return reviews

    results = await ddgs_gate.search(f'"{company}" {city} avis clients google'.strip(), max_results=5)
    for r in results:
        body = r.get("body", "").lower()

        rating_match = re.search(r'(\d[.,]\d)\s*(?:/5|étoiles?|stars?)', body)
        if rating_match and reviews["rating"] is None:
            reviews["rating"] = float(rating_match.group(1).replace(",", "."))

        count_match = re.search(r'(\d+)\s*(?:avis|reviews?|commentaires?)', body)
        if count_match:
            reviews["review_count"] = max(reviews["review_count"], int(count_match.group(1)))

        for phrase in _PAIN_REVIEW_PHRASES:
            if phrase in body:
                reviews["pain_signals"].append(f"Avis mentionnant « {phrase} »")

    return reviews


async def _find_social_fallback(company: str) -> Dict[str, Optional[str]]:
    """Only called when the lead's own website had zero social links — one capped DDGS query."""
    social: Dict[str, Optional[str]] = {"instagram": None, "facebook": None, "linkedin": None}
    if not company:
        return social

    results = await ddgs_gate.search(
        f'"{company}" site:instagram.com OR site:facebook.com OR site:linkedin.com', max_results=5
    )
    for r in results:
        url = r.get("href", "")
        url_lower = url.lower()
        if "instagram.com" in url_lower and not social["instagram"]:
            social["instagram"] = url
        elif "facebook.com" in url_lower and not social["facebook"]:
            social["facebook"] = url
        elif "linkedin.com" in url_lower and not social["linkedin"]:
            social["linkedin"] = url

    return social


def _apply_fallback_research(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Used when research times out or crashes — keeps the pipeline moving with safe defaults
    instead of dropping the lead or hanging the batch."""
    lead["has_website"] = bool(lead.get("website"))
    lead["has_quote_form"] = False
    lead["google_rating"] = None
    lead["google_reviews"] = 0
    lead["has_instagram"] = lead.get("has_instagram") or ""
    lead["has_facebook"] = lead.get("has_facebook") or ""
    lead["has_linkedin"] = lead.get("has_linkedin") or ""
    lead["digital_maturity"] = 2
    lead["pain_points"] = json.dumps(["Analyse automatique incomplète (site trop lent à charger) — vérification manuelle recommandée."], ensure_ascii=False)
    lead["pitch_angle"] = _PITCH_TEMPLATES["default"].format(company=lead.get("company_name", "cette entreprise"))
    lead["custom_opening"] = f"Bonjour, je vous contacte au sujet de {lead.get('company_name', 'votre entreprise')}..."
    lead["urgency_score"] = 5
    lead["estimated_quotes"] = _estimate_quotes(lead)
    # Free/instant, no network — no reason to skip this even on a timeout.
    lead["legal_form"] = _extract_legal_form(lead.get("company_name", ""))
    lead["business_description"] = (
        f"Entreprise du secteur {_niche_label(lead.get('niche', ''))} "
        f"à {lead.get('city') or lead.get('canton', 'Suisse romande')}."
    )
    lead["status"] = "researched"
    lead["layer_reached"] = 5
    # This is the fallback path (timeout/crash), not real research — main.py's
    # final-gate loop requires research_complete=True to count a lead toward
    # the delivered target, so a lead that only ever hit this path can't sneak
    # through on default-filled data.
    lead["research_complete"] = False

    if lead.get("phone"):
        update_lead(lead["phone"], {
            "has_website": lead["has_website"], "has_quote_form": lead["has_quote_form"],
            "digital_maturity": lead["digital_maturity"], "pain_points": lead["pain_points"],
            "pitch_angle": lead["pitch_angle"], "custom_opening": lead["custom_opening"],
            "urgency_score": lead["urgency_score"], "estimated_quotes": lead["estimated_quotes"],
            "legal_form": lead["legal_form"], "business_description": lead["business_description"],
            "status": "researched", "layer_reached": 5, "research_complete": False,
        })
    return lead


async def _research_lead_inner(lead: Dict[str, Any]) -> Dict[str, Any]:
    company = lead.get("company_name", "Unknown")
    city = lead.get("city", "") or lead.get("canton", "")
    website = lead.get("website", "")

    web_data = _empty_web_data()
    if website:
        try:
            web_data = await analyze_website(website)
        except Exception as e:
            logger.warning(f"Website analysis failed for {company}: {e}")

    # Prefer social links found directly on the company's own site — only fall back
    # to a DDGS search if the site had nothing (or there was no site at all).
    # Both DDGS steps below get their OWN short timeout, separate from the overall
    # per-lead budget: the shared ddgs_gate only allows 2 concurrent DDGS calls
    # globally, so under load (or while DDGS is degraded) a lead could otherwise
    # queue for its turn long enough to blow the whole per-lead timeout — dragging
    # a lead into full fallback mode even though its (non-DDGS) site analysis
    # completed in seconds. Capping each optional step keeps that from happening:
    # worst case we just skip reviews/social-fallback and keep the real analysis.
    social: Dict[str, Optional[str]] = dict(web_data.get("social_links", {}))
    for key in ("instagram", "facebook", "linkedin"):
        social.setdefault(key, None)
    if not any(social.values()):
        try:
            fallback_social = await asyncio.wait_for(_find_social_fallback(company), timeout=8)
            social.update({k: v for k, v in fallback_social.items() if v})
        except asyncio.TimeoutError:
            pass

    try:
        reviews = await asyncio.wait_for(_find_reviews(company, city), timeout=8)
    except asyncio.TimeoutError:
        reviews = {"rating": None, "review_count": 0, "pain_signals": []}

    # Legal form is free/instant (derived from the name itself). Zefix is a plain
    # government API (not DDGS), so it gets its own short timeout rather than
    # sharing the contentious ddgs_gate — but still bounded, still never blocks.
    legal_form = _extract_legal_form(company)
    zefix_uid, zefix_status, zefix_purpose, zefix_legal_form = "", "", "", ""
    try:
        zefix_result = await asyncio.wait_for(asyncio.to_thread(zefix_lookup, company), timeout=10)
        if zefix_result:
            zefix_uid = zefix_result.get("uid", "")
            zefix_status = zefix_result.get("status", "")
            zefix_purpose = zefix_result.get("purpose", "")
            zefix_legal_form = zefix_result.get("legal_form", "") or ""
    except Exception as e:
        logger.debug(f"Zefix lookup skipped for {company}: {e}")

    # Business description: prefer the site's own marketing copy, fall back to the
    # officially registered purpose, fall back to a generic niche-based line so the
    # field is never blank.
    business_description = (
        web_data.get("meta_description")
        or zefix_purpose
        or f"Entreprise du secteur {_niche_label(lead.get('niche', ''))} à {city or lead.get('canton', 'Suisse romande')}."
    )

    digital_maturity = _compute_digital_maturity(web_data, social)
    pain_points = _compute_pain_points(lead, web_data, reviews)
    urgency_score = _compute_urgency(web_data, digital_maturity, reviews)
    category = _dominant_pain_category(web_data)

    city_suffix = f" à {city}" if city else ""
    pitch_angle = _PITCH_TEMPLATES[category].format(company=company)
    custom_opening = _OPENING_TEMPLATES[category].format(
        company=company, city_suffix=city_suffix, niche_label=_niche_label(lead.get("niche", ""))
    )

    lead["has_website"] = web_data.get("reachable", False)
    lead["has_quote_form"] = web_data.get("has_quote_form", False)
    lead["google_rating"] = reviews.get("rating")
    lead["google_reviews"] = reviews.get("review_count", 0)
    lead["has_instagram"] = social.get("instagram") or ""
    lead["has_facebook"] = social.get("facebook") or ""
    lead["has_linkedin"] = social.get("linkedin") or ""
    lead["digital_maturity"] = digital_maturity
    lead["pain_points"] = json.dumps(pain_points, ensure_ascii=False)
    lead["pitch_angle"] = pitch_angle
    lead["custom_opening"] = custom_opening
    lead["urgency_score"] = urgency_score
    lead["estimated_quotes"] = _estimate_quotes(lead)
    lead["legal_form"] = legal_form
    lead["business_description"] = business_description
    if zefix_uid:
        lead["zefix_uid"] = zefix_uid
        lead["zefix_status"] = zefix_status
    # Size signals gathered here, consumed by Layer 6's company-size estimate
    # (kept in-memory on the lead; the lead object flows straight into Layer 6
    # in the same run). See utils/company_size.py.
    if zefix_legal_form:
        lead["zefix_legal_form"] = zefix_legal_form
    lead["team_headcount_hint"] = web_data.get("team_headcount_hint")
    lead["mentions_team"] = web_data.get("mentions_team", False)
    lead["web_dm_candidate_count"] = len(web_data.get("decision_maker_candidates", []))
    lead["status"] = "researched"
    lead["layer_reached"] = 5
    # This lead went through the real analysis, not the timeout/crash fallback —
    # main.py's final-gate loop requires this to count the lead toward the
    # delivered target.
    lead["research_complete"] = True
    # Stashed for Layer 6 so it can reuse this crawl instead of re-fetching the site.
    lead["_dm_candidates"] = web_data.get("decision_maker_candidates", [])
    if not lead.get("email") and web_data.get("contact_emails"):
        lead["email"] = web_data["contact_emails"][0]

    if lead.get("phone"):
        update_lead(lead["phone"], {
            "has_website": lead["has_website"],
            "has_quote_form": lead["has_quote_form"],
            "google_rating": lead["google_rating"],
            "google_reviews": lead["google_reviews"],
            "has_instagram": lead["has_instagram"],
            "has_facebook": lead["has_facebook"],
            "has_linkedin": lead["has_linkedin"],
            "digital_maturity": lead["digital_maturity"],
            "pain_points": lead["pain_points"],
            "pitch_angle": lead["pitch_angle"],
            "custom_opening": lead["custom_opening"],
            "urgency_score": lead["urgency_score"],
            "estimated_quotes": lead["estimated_quotes"],
            "legal_form": lead["legal_form"],
            "business_description": lead["business_description"],
            "zefix_uid": lead.get("zefix_uid"),
            "zefix_status": lead.get("zefix_status"),
            "email": lead.get("email"),
            "status": "researched",
            "layer_reached": 5,
            "research_complete": True,
        })

    return lead


async def research_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Perform deep, rule-based public-info research on a single lead. Hard-capped at
    config.LEAD_RESEARCH_TIMEOUT so one slow/hostile site can never stall the batch."""
    try:
        return await asyncio.wait_for(_research_lead_inner(lead), timeout=config.LEAD_RESEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"Research timed out for {lead.get('company_name', 'Unknown')} — applying fallback defaults.")
        return _apply_fallback_research(lead)
    except Exception as e:
        logger.error(f"Research crashed for {lead.get('company_name', 'Unknown')}: {e}")
        return _apply_fallback_research(lead)


async def batch_research(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process all qualified leads through deep research, in parallel (bounded by
    config.RESEARCH_CONCURRENCY — no external LLM rate limit to respect anymore)."""
    semaphore = asyncio.Semaphore(config.RESEARCH_CONCURRENCY)
    completed_research = 0

    with Progress(TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TextColumn("{task.completed}/{task.total}")) as progress:
        task = progress.add_task("Researching leads...", total=len(leads))

        async def process_lead(i, lead):
            nonlocal completed_research
            async with semaphore:
                check_cancellation()
                company = lead.get("company_name", "Unknown")
                console.print(f"  [{i+1}/{len(leads)}] Researching [cyan]{company}[/cyan]...")

                result = await research_lead(lead)

                urgency = result.get("urgency_score", 0)
                urgency_color = "red" if urgency >= 8 else "yellow" if urgency >= 5 else "green"
                console.print(f"    -> {company}: Urgency: [{urgency_color}]{urgency}/10[/{urgency_color}] | "
                             f"Digital: {result.get('digital_maturity', '?')}/5")

                completed_research += 1
                update_state({"leads_researched": completed_research})

                progress.advance(task)
                return result

        tasks = [process_lead(i, lead) for i, lead in enumerate(leads)]
        researched = await asyncio.gather(*tasks)

    return researched
