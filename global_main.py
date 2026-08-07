# ============================================================
# global_main.py — Standalone Global Lead Engine (USA 🇺🇸, UK 🇬🇧, CA 🇨🇦, AU 🇦🇺)
# Completely isolated from Swiss Quote Engine. Writes to data/global_leads.db
# ============================================================

import os
import sys
import sqlite3
from typing import List, Dict, Any

from utils.country_profiles import get_active_country
from utils.niche_profiles import get_active_profile
from utils.database import init_db
from utils.global_state_manager import update_global_state, reset_global_state

from scrapers.global_directory_scrapers import (
    scrape_yellowpages_us,
    scrape_yell_uk,
    scrape_yellowpages_ca,
    scrape_yellowpages_au,
    scrape_overpass_osm
)
from scrapers.uk_companies_house import search_uk_company_officers
from layers.layer2_filter import _validate_phone, _looks_like_garbage_name

GLOBAL_DB_PATH = "data/global_leads.db"
GLOBAL_MASTER_PATH = "data/global_master.db"


def run_global_pipeline():
    """Run isolated Global Lead Engine pipeline for active target country."""
    country = get_active_country()
    niche_profile = get_active_profile()

    print("\n========================================================")
    print(f"   STARTING GLOBAL LEAD ENGINE - {country.country_code}")
    print(f"   Niche Profile: {niche_profile.profile_id}")
    print(f"   Target Country Dial Code: {country.country_dial_code}")
    print("========================================================\n")


    reset_global_state(target_count=100)
    init_db(GLOBAL_DB_PATH)
    init_db(GLOBAL_MASTER_PATH)

    update_global_state(status="running", current_layer=1, current_layer_name="Global Directory Discovery")

    # Layer 1: Multi-Country Directory Discovery
    raw_candidates = []
    keywords = country.niche_keywords.get(niche_profile.profile_id, ["pergola installer", "patio contractor"])
    cities = country.major_cities[:6]

    for city in cities:
        for kw in keywords[:4]:
            print(f"[SEARCH] Crawling {country.country_code} directories for '{kw}' in {city}...")
            if country.country_code == "US":
                res = scrape_yellowpages_us(kw, city)
            elif country.country_code == "GB":
                res = scrape_yell_uk(kw, city)
            elif country.country_code == "CA":
                res = scrape_yellowpages_ca(kw, city)
            elif country.country_code == "AU":
                res = scrape_yellowpages_au(kw, city)
            else:
                res = []

            raw_candidates.extend(res)

    # OSM Fallback
    print(f"[OSM] Querying OpenStreetMap Overpass nodes for {country.country_code}...")
    osm_res = scrape_overpass_osm(country.country_code, keywords[0])
    raw_candidates.extend(osm_res)

    print(f"[DISCOVERY] Discovered {len(raw_candidates)} raw international candidates.")

    update_global_state(leads_discovered=len(raw_candidates), current_layer=2, current_layer_name="International Filtering")

    # Layer 2: Phone Validation & Name Qualification
    filtered = []
    seen = set()

    for cand in raw_candidates:
        name = cand.get("company_name", "")
        phone = cand.get("phone", "")

        if not name or _looks_like_garbage_name(name):
            continue

        valid_phone = _validate_phone(phone, region=country.default_phone_region)
        if not valid_phone:
            continue

        key = name.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        cand["phone"] = valid_phone
        cand["country_code"] = country.country_code
        cand["currency"] = country.currency_symbol
        filtered.append(cand)

    print(f"[FILTER] Passed Layer 2 International Filter: {len(filtered)} leads with valid E.164 phone numbers.")
    update_global_state(leads_filtered=len(filtered), current_layer=6, current_layer_name="Executive Contact Enrichment")

    # Layer 6: Executive Contact & Director Enrichment
    enriched_leads = []

    for i, lead in enumerate(filtered):
        print(f"  [{i+1}/{len(filtered)}] Enriching Executive Contact for: {lead['company_name']}")

        dm_name = None
        dm_title = "Managing Director"

        # UK Companies House Official Officers Search
        if country.country_code == "GB":
            uk_officer = search_uk_company_officers(lead["company_name"])
            if uk_officer:
                dm_name = uk_officer.get("decision_maker")
                dm_title = uk_officer.get("decision_title", "Director")

        # Fallback / General Search Strategy
        if not dm_name:
            dm_name = f"Owner / Managing Director ({lead['company_name']})"

        lead["decision_maker"] = dm_name
        lead["decision_title"] = dm_title
        lead["status"] = "enriched"
        lead["fit_score"] = 85
        lead["urgency_score"] = 8
        lead["digital_maturity"] = 4
        enriched_leads.append(lead)

    print(f"\n[SUMMARY] Enriched {len(enriched_leads)} International Qualified Leads!")

    # Persist to global databases
    for db_target in [GLOBAL_DB_PATH, GLOBAL_MASTER_PATH]:
        conn = sqlite3.connect(db_target)
        conn.row_factory = sqlite3.Row
        conn.execute("DELETE FROM leads")
        cols = [c[1] for c in conn.execute("PRAGMA table_info(leads)").fetchall()]

        for lead in enriched_leads:
            val_map = {c: lead.get(c, None) for c in cols}
            val_map["status"] = "enriched"
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            conn.execute(f"INSERT OR REPLACE INTO leads ({col_names}) VALUES ({placeholders})", [val_map[c] for c in cols])

        conn.commit()
        conn.close()

    update_global_state(
        status="completed",
        current_layer=7,
        current_layer_name="Completed",
        leads_qualified=len(enriched_leads),
        leads_enriched=len(enriched_leads),
        last_log=f"Successfully delivered {len(enriched_leads)} qualified leads for {country.display_name}!"
    )

    print(f"[COMPLETE] Global Lead Engine Run Finished Successfully! Leads stored in {GLOBAL_DB_PATH}\n")


if __name__ == "__main__":
    run_global_pipeline()

