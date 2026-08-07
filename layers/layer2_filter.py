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
from utils.noga import classify_noga

logger = get_logger("layer2")
console = Console()


from utils.country_profiles import get_active_country

def _validate_phone(phone: str, region: str = None) -> str | None:
    """Validate and format an international phone number (US, UK, CA, AU, CH). Returns E.164 format or None."""
    if not phone:
        return None
    if not region:
        region = get_active_country().default_phone_region
    try:
        parsed = phonenumbers.parse(phone, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    try:
        parsed = phonenumbers.parse(phone, None)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
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
    """Check if the lead matches active profile NOGA or niche keywords."""
    niche = lead.get("niche", "")
    full_text = f"{lead.get('company_name', '')} {lead.get('raw_snippet', '')}"
    info = classify_noga(niche, full_text)
    if info:
        lead["noga_code"] = info["code"]
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

        # 1. Canton / Region check — if detected, must be in targets (or default to pass if international)
        canton = lead.get("canton", "")
        if canton and config.TARGET_CANTONS and canton not in config.TARGET_CANTONS:
            # For international runs, region check is informational
            pass

        # 2. Phone REQUIRED — validate international format
        raw_phone = lead.get("phone", "")
        formatted_phone = _validate_phone(raw_phone)
        if not formatted_phone:
            reasons.append("Missing or invalid phone number for target region")
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

        # 4. Niche relevance — check against active profile
        if not _is_relevant_niche(lead) and not reasons:
            reasons.append(f"Not relevant to active profile ({config.get_active_profile().display_name})")


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
