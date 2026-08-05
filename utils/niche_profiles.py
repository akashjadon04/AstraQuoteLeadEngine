# utils/niche_profiles.py — Multi-Niche Scraper Profile Registry
# Supports single-click profile switching between:
# 1. Plumbing / HVAC / Sanitaire (NOGA 43.22)
# 2. Pergolas / Awnings / Stores / Protection Solaire (NOGA 43.32 / 43.21)

import os
import json
from typing import Dict, List, Any

class NicheProfile:
    def __init__(
        self,
        profile_id: str,
        display_name: str,
        icon: str,
        noga_codes: List[str],
        primary_niches: List[str],
        secondary_niches: List[str],
        trade_keywords: Dict[str, List[str]],
        exclude_keywords: List[str],
        zefix_search_terms: List[str],
        pitch_angle_template: str,
        description: str
    ):
        self.profile_id = profile_id
        self.display_name = display_name
        self.icon = icon
        self.noga_codes = noga_codes
        self.primary_niches = primary_niches
        self.secondary_niches = secondary_niches
        self.trade_keywords = trade_keywords
        self.exclude_keywords = exclude_keywords
        self.zefix_search_terms = zefix_search_terms
        self.pitch_angle_template = pitch_angle_template
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "icon": self.icon,
            "noga_codes": self.noga_codes,
            "primary_niches": self.primary_niches,
            "secondary_niches": self.secondary_niches,
            "zefix_search_terms": self.zefix_search_terms,
            "pitch_angle_template": self.pitch_angle_template,
            "description": self.description
        }


# Define Profile 1: Plumbing, Sanitaire & Chauffage (NOGA 43.22)
PROFILE_PLUMBING_HVAC = NicheProfile(
    profile_id="plumbing_hvac",
    display_name="Plomberie & Chauffage",
    icon="🔧",
    noga_codes=["43.22", "43.22A", "43.22B"],
    primary_niches=[
        "plombier", "plomberie", "sanitaire", "installateur sanitaire", 
        "chauffagiste", "chauffage", "dépannage plomberie", "installation sanitaire"
    ],
    secondary_niches=[
        "installations sanitaires", "technique du bâtiment", "génie sanitaire",
        "pompe à chaleur", "installation thermique"
    ],
    trade_keywords={
        "plomberie": ["plombier", "plomberie", "tuyauterie", "débouchage", "debouchage", "canalisation", "canalisations", "fuite d'eau"],
        "sanitaire": ["sanitaire", "installateur sanitaire", "installation sanitaire", "installations sanitaires", "salle de bain", "robinetterie", "génie sanitaire", "genie sanitaire"],
        "chauffage": ["chauffagiste", "chauffage", "hvac", "thermique", "chaudière", "chaudiere", "pompe à chaleur", "pompe a chaleur", "installation thermique", "technique du bâtiment", "climatisation", "ventilation"]
    },
    exclude_keywords=[
        "carrelage", "carreleur", "peinture", "peintre", "maçonnerie", "maconnerie",
        "serrurerie", "serrurier", "vitrerie", "vitrier", "électricité", "electricite",
        "piscine", "piscines", "nettoyage", "jardinage", "paysagiste", "toiture", "couvreur",
        "charpente", "menuiserie", "étanchéité", "imprimerie", "avocat", "médecin",
        "coiffure", "esthétique", "garage", "automobile", "auto", "carrosserie",
        "restaurant", "hôtel", "immobilier", "fiduciaire", "informatique", "telecom",
        "transport", "demenagement", "vet", "vétérinaire", "pharmacie", "santé",
        "influencer", "interim", "commune", "ortho-team", "consulting"
    ],
    zefix_search_terms=["sanitaire", "chauffage", "plomberie", "installations sanitaires"],
    pitch_angle_template="Automated instant online quoting for emergency calls, heating replacement requests & bathroom lead qualification.",
    description="Targets Swiss plumbing, heating, sanitary and HVAC contractors (NOGA 43.22)."
)


# Define Profile 2: Pergolas, Stores & Protection Solaire (Quote Engine Prototype)
PROFILE_PERGOLAS_AWNINGS = NicheProfile(
    profile_id="pergolas_awnings",
    display_name="Pergolas & Stores (Quote Engine)",
    icon="☀️",
    noga_codes=["43.32", "43.32A", "43.21", "43.99"],
    primary_niches=[
        "pergola", "pergolas", "store banne", "stores bannes", "protection solaire",
        "installateur de stores", "pergola bioclimatique", "volets roulants", "store extérieur"
    ],
    secondary_niches=[
        "fermetures", "baies vitrées", "toile de store", "aménagement extérieur",
        "terrasse et jardin", "store vénitien", "véranda", "parasol professionnel"
    ],
    trade_keywords={
        "pergola": ["pergola", "pergolas", "bioclimatique", "pergola aluminium", "structure terrasse", "véranda", "veranda"],
        "stores": ["store", "stores", "store banne", "stores bannes", "volet", "volets", "volets roulants", "toile de store", "store vénitien"],
        "protection_solaire": ["protection solaire", "pare-soleil", "ombrage", "baies vitrées", "fermetures", "aménagement extérieur", "terrasse"]
    },
    exclude_keywords=[
        "plomberie", "plombier", "sanitaire", "chauffage", "chauffagiste", "peinture",
        "peintre", "nettoyage", "garage", "auto", "carrosserie", "restaurant",
        "hôtel", "immobilier", "fiduciaire", "informatique", "médecin", "pharmacie",
        "vétérinaire", "vet", "coiffure", "esthétique", "avocat", "interim", "consulting"
    ],
    zefix_search_terms=["stores", "pergola", "protection solaire", "fermetures"],
    pitch_angle_template="Quote Engine AI Integration: Turn homeowner terrace photos into instant 2-minute pergola & awning quotes with monthly financing illustrations (CHF 300/mo).",
    description="Targets Swiss pergola, awning, blinds, and sun-protection installers matching your Quote Engine prototype."
)


PROFILES: Dict[str, NicheProfile] = {
    "plumbing_hvac": PROFILE_PLUMBING_HVAC,
    "pergolas_awnings": PROFILE_PERGOLAS_AWNINGS
}

_PROFILE_STATE_FILE = "data/active_niche_profile.json"


def get_active_profile_id() -> str:
    """Get currently active niche profile ID ('plumbing_hvac' or 'pergolas_awnings')."""
    if os.path.exists(_PROFILE_STATE_FILE):
        try:
            with open(_PROFILE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                pid = data.get("active_profile_id")
                if pid in PROFILES:
                    return pid
        except Exception:
            pass
    return "plumbing_hvac"


def get_active_profile() -> NicheProfile:
    """Get active NicheProfile object."""
    pid = get_active_profile_id()
    return PROFILES.get(pid, PROFILE_PLUMBING_HVAC)


def set_active_profile_id(profile_id: str) -> bool:
    """Set active niche profile ID."""
    if profile_id not in PROFILES:
        return False
    os.makedirs(os.path.dirname(_PROFILE_STATE_FILE) or ".", exist_ok=True)
    with open(_PROFILE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"active_profile_id": profile_id}, f, indent=2)
    return True


def list_profiles() -> List[Dict[str, Any]]:
    """List all available niche profiles with active flag."""
    active_id = get_active_profile_id()
    result = []
    for pid, profile in PROFILES.items():
        d = profile.to_dict()
        d["is_active"] = (pid == active_id)
        result.append(d)
    return result
