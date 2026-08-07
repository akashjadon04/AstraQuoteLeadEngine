# ============================================================
# country_profiles.py — Multi-Country International Profile Engine
# Supports USA 🇺🇸, United Kingdom 🇬🇧, Canada 🇨🇦, Australia 🇦🇺, Switzerland 🇨🇭
# ============================================================

import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any

COUNTRY_STATE_FILE = "data/active_country_profile.json"


@dataclass
class CountryProfile:
    country_code: str          # 'US', 'GB', 'CA', 'AU', 'CH'
    display_name: str          # 'United States 🇺🇸'
    flag_emoji: str            # '🇺🇸'
    default_phone_region: str  # 'US', 'GB', etc.
    country_dial_code: str     # '+1', '+44', etc.
    major_regions: List[str]
    major_cities: List[str]
    niche_keywords: Dict[str, List[str]] # keywords per niche profile ID
    directory_sources: List[str]
    currency_symbol: str       # '$', '£', 'CHF'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "country_code": self.country_code,
            "display_name": self.display_name,
            "flag_emoji": self.flag_emoji,
            "default_phone_region": self.default_phone_region,
            "country_dial_code": self.country_dial_code,
            "major_regions": self.major_regions,
            "major_cities": self.major_cities,
            "directory_sources": self.directory_sources,
            "currency_symbol": self.currency_symbol,
        }


COUNTRY_REGISTRY: Dict[str, CountryProfile] = {
    "US": CountryProfile(
        country_code="US",
        display_name="United States 🇺🇸",
        flag_emoji="🇺🇸",
        default_phone_region="US",
        country_dial_code="+1",
        major_regions=["California", "Texas", "Florida", "New York", "North Carolina", "Georgia", "Arizona", "Washington", "Colorado"],
        major_cities=["Los Angeles", "Miami", "Houston", "Dallas", "Phoenix", "Atlanta", "Charlotte", "Denver", "Seattle", "Austin", "Tampa", "Orlando", "San Diego", "Raleigh"],
        niche_keywords={
            "pergolas_awnings": [
                "pergola contractor", "louvered pergola installer", "patio cover builder",
                "awning installation company", "sunroom contractor", "outdoor living builder",
                "deck and pergola company", "retractable awning installer", "motorized pergola builder"
            ],
            "plumbing_hvac": [
                "plumbing contractor", "hvac contractor", "commercial plumbing service",
                "heating and air conditioning installer", "sanitary contractor"
            ]
        },
        directory_sources=["yellowpages_us", "ddgs_us", "overpass_us", "google_maps_us"],
        currency_symbol="$"
    ),
    "GB": CountryProfile(
        country_code="GB",
        display_name="United Kingdom 🇬🇧",
        flag_emoji="🇬🇧",
        default_phone_region="GB",
        country_dial_code="+44",
        major_regions=["London", "Greater Manchester", "West Midlands", "West Yorkshire", "Scotland", "Wales", "South East", "South West"],
        major_cities=["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Bristol", "Edinburgh", "Sheffield", "Leicester", "Nottingham", "Southampton"],
        niche_keywords={
            "pergolas_awnings": [
                "pergola installer", "patio awning company", "veranda specialist",
                "canopy installer uk", "bioclimatic pergola installer", "garden building company",
                "commercial awning installer", "retractable awning uk", "window blinds and shutters"
            ],
            "plumbing_hvac": [
                "plumbing and heating engineer", "hvac installer uk", "boiler installation company",
                "sanitary engineer uk"
            ]
        },
        directory_sources=["yell_uk", "companies_house_uk", "ddgs_uk", "google_maps_uk"],
        currency_symbol="£"
    ),
    "CA": CountryProfile(
        country_code="CA",
        display_name="Canada 🇨🇦",
        flag_emoji="🇨🇦",
        default_phone_region="CA",
        country_dial_code="+1",
        major_regions=["Ontario", "British Columbia", "Alberta", "Quebec"],
        major_cities=["Toronto", "Vancouver", "Calgary", "Montreal", "Ottawa", "Edmonton", "Mississauga", "Winnipeg"],
        niche_keywords={
            "pergolas_awnings": [
                "pergola builder canada", "patio cover installer canada", "awning contractor canada",
                "louvered pergola installer", "outdoor shade solutions", "sunroom builder ontario"
            ],
            "plumbing_hvac": [
                "plumbing contractor canada", "hvac installer canada", "heating contractor ontario"
            ]
        },
        directory_sources=["yellowpages_ca", "ddgs_ca", "google_maps_ca"],
        currency_symbol="$"
    ),
    "AU": CountryProfile(
        country_code="AU",
        display_name="Australia 🇦🇺",
        flag_emoji="🇦🇺",
        default_phone_region="AU",
        country_dial_code="+61",
        major_regions=["New South Wales", "Victoria", "Queensland", "Western Australia", "South Australia"],
        major_cities=["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Gold Coast", "Canberra"],
        niche_keywords={
            "pergolas_awnings": [
                "pergola builders australia", "patio builders sydney", "opening roof pergolas",
                "outdoor blinds and awnings", "louvre roof installer australia", "carport and patio builder"
            ],
            "plumbing_hvac": [
                "plumbing contractor australia", "air conditioning installer sydney"
            ]
        },
        directory_sources=["yellowpages_au", "ddgs_au", "google_maps_au"],
        currency_symbol="$"
    ),
    "CH": CountryProfile(
        country_code="CH",
        display_name="Switzerland 🇨🇭",
        flag_emoji="🇨🇭",
        default_phone_region="CH",
        country_dial_code="+41",
        major_regions=["Genève", "Vaud", "Valais", "Neuchâtel", "Jura", "Zürich", "Bern"],
        major_cities=["Genève", "Lausanne", "Sion", "Neuchâtel", "Delémont", "Zürich", "Bern", "Vernier", "Yverdon-les-Bains"],
        niche_keywords={
            "pergolas_awnings": [
                "pergola", "pergolas", "store banne", "stores bannes", "protection solaire",
                "installateur de stores", "pergola bioclimatique", "volets roulants", "store extérieur"
            ],
            "plumbing_hvac": [
                "plomberie", "sanitaire", "chauffage", "ferblanterie", "climatisation"
            ]
        },
        directory_sources=["local_ch", "zefix_ch", "shab_ch", "ddgs_ch"],
        currency_symbol="CHF"
    )
}


def get_active_country_code() -> str:
    """Get active country code from state file or default to US/CH."""
    if os.path.exists(COUNTRY_STATE_FILE):
        try:
            with open(COUNTRY_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                code = data.get("active_country_code")
                if code in COUNTRY_REGISTRY:
                    return code
        except Exception:
            pass
    return "US"  # Default active country


def get_active_country() -> CountryProfile:
    """Get active CountryProfile object."""
    code = get_active_country_code()
    return COUNTRY_REGISTRY.get(code, COUNTRY_REGISTRY["US"])


def set_active_country_code(country_code: str) -> bool:
    """Set active country code."""
    if country_code in COUNTRY_REGISTRY:
        os.makedirs(os.path.dirname(COUNTRY_STATE_FILE), exist_ok=True)
        with open(COUNTRY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"active_country_code": country_code}, f, indent=2)
        return True
    return False


def list_countries() -> List[Dict[str, Any]]:
    """List all registered countries."""
    active = get_active_country_code()
    result = []
    for code, country in COUNTRY_REGISTRY.items():
        d = country.to_dict()
        d["is_active"] = (code == active)
        result.append(d)
    return result
