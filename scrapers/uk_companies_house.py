# ============================================================
# uk_companies_house.py — UK Companies House Free Public API
# Searches UK official registry for company officers and directors
# ============================================================

import os
import requests
from typing import Dict, Any, Optional

# Public free search endpoint
SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"
OFFICERS_URL = "https://api.company-information.service.gov.uk/company/{company_number}/officers"

# UK Companies House free API key (or public search fallback)
API_KEY = os.environ.get("UK_COMPANIES_HOUSE_API_KEY", "")


def search_uk_company_officers(company_name: str) -> Optional[Dict[str, Any]]:
    """
    Search UK Companies House API for company officer / director.
    Returns dict with 'decision_maker', 'decision_title', 'company_number' if found.
    """
    if not company_name or len(company_name.strip()) < 3:
        return None

    headers = {}
    if API_KEY:
        # Companies House uses HTTP Basic Auth with API key as username
        headers["Authorization"] = f"Basic {API_KEY}"

    try:
        # Search company
        params = {"q": company_name, "items_per_page": 3}
        resp = requests.get(SEARCH_URL, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return None

            company = items[0]
            company_number = company.get("company_number")
            company_title = company.get("title")

            if not company_number:
                return None

            # Fetch officers
            officer_resp = requests.get(
                OFFICERS_URL.format(company_number=company_number),
                headers=headers,
                timeout=8
            )

            if officer_resp.status_code == 200:
                off_data = officer_resp.json()
                officers = off_data.get("items", [])
                for officer in officers:
                    role = officer.get("officer_role", "").lower()
                    if "director" in role or "member" in role or "owner" in role:
                        raw_name = officer.get("name", "")
                        # UK format is "SURNAME, Firstname Middle"
                        clean_name = raw_name
                        if "," in raw_name:
                            parts = raw_name.split(",", 1)
                            clean_name = f"{parts[1].strip()} {parts[0].strip()}"

                        return {
                            "decision_maker": clean_name,
                            "decision_title": officer.get("officer_role", "Director").title(),
                            "company_number": company_number,
                            "official_name": company_title,
                        }
    except Exception:
        pass

    return None
