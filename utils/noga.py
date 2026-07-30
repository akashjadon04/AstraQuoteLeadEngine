# ============================================================
# noga.py — Swiss NOGA Activity Classification (Nomenclature Générale des Activités)
# Official Swiss economic activity classification for B2B targeting.
# AstraQuote Target Domain: NOGA 4322 (Plumbing, Heating, Sanitation, HVAC)
# ============================================================

from typing import Dict, Any, Optional

NOGA_432201 = "NOGA 432201 — Installation sanitaire & Plomberie"
NOGA_432202 = "NOGA 432202 — Installation de chauffage & Climatisation"

_PLUMBING_STEMS = [
    "plomb", "sanitaire", "tuyau", "robinet", "salle de bain",
    "installation sanitaire", "installations sanitaires", "dépannage plomberie",
    "depannage plomberie", "génie sanitaire", "genie sanitaire", "canalisation",
    "débouchage", "debouchage", "installateur sanitaire", "ferblanterie sanitaire",
    "ferblanterie-sanitaire"
]

_HEATING_STEMS = [
    "chauffag", "hvac", "thermique", "chaudière", "chaudiere",
    "calorifère", "pompe à chaleur", "pompe a chaleur", "installation thermique",
    "climatisation", "ventilation", "wärmetechnik", "warmetechnik", "haustechnik"
]

_INVALID_NOGAS = [
    "carrelage", "carreleur", "peinture", "peintre", "maçonnerie", "maçon", "macon",
    "menuiserie", "menuisier", "serrurerie", "serrurier", "vitrerie", "vitrier",
    "électricité", "électricien", "electricien", "nettoyage", "paysagiste",
    "jardinier", "piscine", "toiture", "étanchéité", "étanchéiste", "échafaudage",
    "architecture", "architecte", "ingénieur", "immobilier"
]


def classify_noga(niche: str, text: str = "") -> Optional[Dict[str, str]]:
    """
    Classify a business into official Swiss NOGA 4322 codes.
    Returns dict with 'code', 'label' if it matches NOGA 4322, or None if not relevant.
    """
    full_text = f"{niche} {text}".lower()

    # Reject if explicit non-plumbing trade with no plumbing keywords
    for invalid in _INVALID_NOGAS:
        if invalid in full_text:
            # Only allow if it ALSO has explicit plumbing/sanitary/heating keywords
            has_plumbing = any(stem in full_text for stem in _PLUMBING_STEMS)
            has_heating = any(stem in full_text for stem in _HEATING_STEMS)
            if not (has_plumbing or has_heating):
                return None

    # Match NOGA 432201 (Sanitaire / Plomberie)
    if any(stem in full_text for stem in _PLUMBING_STEMS) or niche in ("plomberie", "sanitaire", "ferblanterie"):
        return {
            "code": "432201",
            "label": NOGA_432201
        }

    # Match NOGA 432202 (Chauffage / Climatisation)
    if any(stem in full_text for stem in _HEATING_STEMS) or niche in ("chauffage", "climatisation"):
        return {
            "code": "432202",
            "label": NOGA_432202
        }

    return None
