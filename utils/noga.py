# ============================================================
# noga.py — Dynamic Swiss NOGA Activity Classification
# Supports both NOGA 43.22 (Plomberie/Sanitaire/Chauffage) and NOGA 43.32/43.21 (Pergolas/Stores/Protection Solaire)
# ============================================================

from typing import Dict, Any, Optional
from utils.niche_profiles import get_active_profile

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

_PERGOLA_STORE_STEMS = [
    "pergola", "pergolas", "store", "stores", "store banne", "stores bannes",
    "protection solaire", "volet", "volets", "volets roulants", "bioclimatique",
    "toile de store", "store extérieur", "store exterieur", "store vénitien", "store venitien",
    "pare-soleil", "ombrage", "baies vitrées", "fermetures", "véranda", "veranda", "parasol"
]


def classify_noga(niche: str, text: str = "") -> Optional[Dict[str, str]]:
    """
    Classify a business into official Swiss NOGA codes matching active profile.
    """
    profile = get_active_profile()
    full_text = f"{niche} {text}".lower()

    if profile.profile_id == "pergolas_awnings":
        if any(stem in full_text for stem in _PERGOLA_STORE_STEMS) or any(k in full_text for k in profile.primary_niches):
            return {
                "code": "43.32",
                "sub_code": "43.32A",
                "legacy_code": "433200",
                "label": "NOGA 43.32 — Menuiserie, Stores & Protection Solaire"
            }
        return None
    else:
        # Default: plumbing_hvac
        if any(stem in full_text for stem in _PLUMBING_STEMS) or niche in ("plomberie", "sanitaire", "ferblanterie"):
            return {
                "code": "43.22",
                "sub_code": "43.22A",
                "legacy_code": "432201",
                "label": "NOGA 43.22A — Installation sanitaire & Plomberie"
            }
        if any(stem in full_text for stem in _HEATING_STEMS) or niche in ("chauffage", "climatisation"):
            return {
                "code": "43.22",
                "sub_code": "43.22B",
                "legacy_code": "432202",
                "label": "NOGA 43.22B — Installation de chauffage & Climatisation"
            }
        return None
