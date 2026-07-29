# ============================================================
# layer2_filter.py — Region & Size Filter
# Filter raw leads by canton, phone, niche, and exclusions
# ============================================================

import re
from typing import List, Dict, Tuple, Any

import phonenumbers
from rich.console import Console

import config
from utils.logger import get_logger

logger = get_logger("layer2")
console = Console()


def _validate_swiss_phone(phone: str) -> str | None:
    """Validate and format a Swiss phone number. Returns E.164 format or None."""
    if not phone:
        return None
    try:
        parsed = phonenumbers.parse(phone, "CH")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


_GARBAGE_NAME_RE = re.compile(
    r"t[ée]l\s*[:.]|\b0\d{2}[\s.]\d{3}[\s.]\d{2}[\s.]\d{2}\b|"
    r"les\s+\d+\s+meilleurs|inscriptions\s+pour|search\s+in\s+google\s+maps|"
    r"tripadvisor|starofservice|renovero|cybo|contacts\s+importants|"
    r"centrale\s+t[ée]l[ée]phonique|handjob|visitable\s+in|offre\s+pour\s+plomberie|"
    r"candidature|accueil\s*-|avis\s+sur|"
    r"(\bhoraires\b|\bheure\b|\bouris\b|\böffnungszeiten\b)|"
    r"(\brésultats\b|\bergebnisse\b|\blocal\.ch\b|\bsearch\.ch\b|\bcylex\b|\beuropages\b)|"
    r"(\bemplois?\b|\bjobscout\b|\bindeed\b|\bjobup\b|\bjobs\b)",
    re.IGNORECASE
)


def _looks_like_garbage_name(company_name: str) -> bool:
    """Check if the extracted company name looks like an SEO title, directory list,
    or non-company text string."""
    return bool(_GARBAGE_NAME_RE.search(company_name or ""))


def _is_relevant_niche(lead: dict) -> bool:
    """Check if the lead is genuinely a plumbing, heating, or sanitaire business.
    CRITICAL: We deliberately do NOT include lead.get('niche') in the text check.
    The niche field is set by detect_niche() which in the past had a fallback to
    'plomberie' for everything — including airports, restaurants, and escort ads.
    That bug is fixed, but even so, checking our own tag is circular reasoning.
    We only check actual content from the web: company_name and raw_snippet."""
    name_lower = (lead.get("company_name") or "").lower()
    snippet_lower = (lead.get("raw_snippet") or "").lower()

    trade_stems = [
        "plomb", "sanitaire", "chauffag", "hvac", "thermique",
        "tuyau", "robinet", "salle de bain", "chaudière", "chaudiere",
        "pompe à chaleur", "pompe a chaleur", "installation sanitaire",
        "installations sanitaires", "dépannage plomberie", "depannage plomberie",
        "génie sanitaire", "genie sanitaire", "technique du bâtiment",
        "technique du batiment", "canalisation", "débouchage", "debouchage",
        "haustechnik", "wärmetechnik", "installateur sanitaire",
    ]

    # Check name first (strongest signal — it's the actual company name from web)
    if any(t in name_lower for t in trade_stems):
        return True

    # Check snippet (from the search result body — also real web content)
    if any(t in snippet_lower for t in trade_stems):
        return True

    return False



def batch_filter(leads: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Filter leads based on strict criteria.
    Returns (passed, eliminated) lists.
    """
    passed = []
    eliminated = []

    for lead in leads:
        reasons = []

        # 1. Canton check — if we detected a canton, it must be in our targets
        canton = lead.get("canton", "")
        if canton and canton not in config.TARGET_CANTONS:
            reasons.append(f"Canton '{canton}' not in targets")

        # 2. Phone REQUIRED — validate Swiss format
        raw_phone = lead.get("phone", "")
        formatted_phone = _validate_swiss_phone(raw_phone)
        if not formatted_phone:
            reasons.append("Missing or invalid Swiss phone number")
        else:
            lead["phone"] = formatted_phone

        # 2.5. Company name must actually be a name, not a scraped SEO snippet
        # with an embedded phone number — see _looks_like_garbage_name.
        if _looks_like_garbage_name(lead.get("company_name", "")):
            reasons.append("Company name looks like a scraped snippet, not a real business name (embedded phone number)")

        # 3. Exclude keywords in company name or snippet
        name_lower = lead.get("company_name", "").lower()
        snippet_lower = lead.get("raw_snippet", "").lower()
        full_text = f"{name_lower} {snippet_lower}"
        for kw in config.EXCLUDE_KEYWORDS:
            if kw.lower() in full_text:
                reasons.append(f"Excluded keyword: '{kw}'")
                break

        # 4. Niche relevance — must relate to plumbing/HVAC/sanitaire
        if not _is_relevant_niche(lead) and not reasons:
            reasons.append("Not in a relevant trade niche")

        # 5. Flag for size check in Layer 5
        lead["needs_size_check"] = True

        if reasons:
            lead["elimination_reasons"] = reasons
            eliminated.append(lead)
        else:
            passed.append(lead)

    console.print(f"  ✓ Passed: [green]{len(passed)}[/green] | Eliminated: [red]{len(eliminated)}[/red]")

    # Log top elimination reasons
    reason_counts: dict[str, int] = {}
    for lead in eliminated:
        for r in lead.get("elimination_reasons", []):
            reason_counts[r] = reason_counts.get(r, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1])[:5]:
        console.print(f"    → {reason}: [dim]{count}[/dim]")

    return passed, eliminated
