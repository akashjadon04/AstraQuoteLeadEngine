# ============================================================
# zefix_client.py — Swiss Official Commercial Registry Lookup
# Zefix (zefix.admin.ch) is Switzerland's federal company registry.
# Verified live against real leads during development: it reliably
# returns UID, registration status, and the company's official
# registered business purpose — but NOT employee counts (that data
# doesn't exist in any free, automatable Swiss source for small
# businesses; confirmed by testing 11 real trade-company websites
# for self-published headcounts and finding zero).
#
# This is a plain government REST API (not a scraped search engine
# like DDGS), so it doesn't need the circuit-breaker treatment —
# just a polite rate limit, a hard timeout, and "never raises."
# Synchronous by design (like SearchChClient) — callers wrap it in
# asyncio.to_thread.
# ============================================================

import re
import threading
import time
from typing import Any, Dict, Optional

import httpx

from utils.logger import get_logger

logger = get_logger("Zefix")

_BASE_URL = "https://www.zefix.admin.ch/ZefixREST/api/v1"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# One shared, connection-pooled client instead of a fresh one per lookup —
# see utils/shab_client.py for why: many concurrent leads each opening their
# own client is what produced live "getaddrinfo failed" bursts under load.
_client_lock = threading.Lock()
_client: Optional[httpx.Client] = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=10.0)
    return _client

_SUFFIX_RE = re.compile(
    r"\b(S\.?A\.?|S\.?à\.?r\.?l\.?|Sarl|Sagl|AG|GmbH|SNC|&\s?Cie|&\s?Fils|et\s?Cie)\b\.?,?\s*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)

_last_call = 0.0
_MIN_INTERVAL = 1.0


def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _tokens(name: str) -> set:
    return {w.lower() for w in _WORD_RE.findall(name) if len(w) > 2}


def _extract_legal_form(entry: Dict[str, Any]) -> str:
    """Pull a human-readable legal-form string out of a Zefix firm record.
    Zefix has shifted this field's shape over time (a nested {name:{fr,de}}
    object, a flat string, or a short code), so this reads whatever's present
    and never raises — an empty string just means 'fall back to name-based
    detection' downstream."""
    lf = entry.get("legalForm") or entry.get("legalFormId") or ""
    if isinstance(lf, dict):
        name = lf.get("name") or lf.get("shortName") or ""
        if isinstance(name, dict):
            return name.get("fr") or name.get("de") or name.get("it") or name.get("en") or ""
        return str(name)
    return str(lf) if lf else ""


def _is_confident_match(query_name: str, candidate_name: str) -> bool:
    """Zefix's search returns loosely related results (e.g. searching 'Portier' can
    surface an unrelated 'Cabinet Médical Michel Portier SA'), and Swiss listings
    aren't consistent about word order ('Portier Eric SA' is registered as 'Eric
    Portier SA'). So: compare as an order-independent set of significant words —
    only accept the match if our query's words are essentially all present in the
    candidate. A partial/wrong match would attach a stranger's registry data to
    this lead, which is worse than having no data at all."""
    query_tokens = _tokens(query_name)
    candidate_tokens = _tokens(candidate_name)
    if not query_tokens:
        return False
    overlap = query_tokens & candidate_tokens
    return len(overlap) / len(query_tokens) >= 0.8


def lookup_company(name: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """Look up a company by name in the official Swiss commercial registry.
    Returns {'uid', 'legal_seat', 'status', 'purpose'} for a confidently-verified
    match, or None if not found / not confident / on any failure — never raises,
    never blocks the caller past `timeout` seconds."""
    if not name or not name.strip():
        return None

    query = _SUFFIX_RE.sub("", name).strip(" -–,")
    if not query:
        return None

    _rate_limit()
    try:
        client = _get_client()
        resp = client.post(
            f"{_BASE_URL}/firm/search.json",
            json={"name": query, "searchType": "contains", "languageKey": "fr"},
            headers=_HEADERS,
        )
        if resp.status_code != 200:
            return None

        results = resp.json().get("list", [])
        if not results:
            return None

        # Prefer an active (EXISTIEREND) registration, and require the name to
        # actually match (see _is_confident_match) before trusting it.
        active = [r for r in results if r.get("status") == "EXISTIEREND"]
        candidates = active or results
        best = next((r for r in candidates if _is_confident_match(name, r.get("name", ""))), None)
        if best is None:
            return None

        purpose = ""
        legal_form = _extract_legal_form(best)
        ehraid = best.get("ehraid")
        if ehraid:
            try:
                detail_resp = client.get(f"{_BASE_URL}/firm/{ehraid}.json", headers=_HEADERS)
                if detail_resp.status_code == 200:
                    detail = detail_resp.json()
                    purpose = detail.get("purpose", "") or ""
                    legal_form = legal_form or _extract_legal_form(detail)
            except Exception:
                pass  # purpose/legal form are bonus fields — a failure here shouldn't drop the whole match

        return {
            "uid": best.get("uidFormatted") or best.get("uid") or "",
            "legal_seat": best.get("legalSeat", ""),
            "status": best.get("status", ""),
            "purpose": purpose,
            # Authoritative legal form from the registry (more reliable than
            # guessing from the company name) — feeds utils/company_size.py.
            "legal_form": legal_form,
        }
    except Exception as e:
        logger.debug(f"Zefix lookup failed for '{name}': {e}")
        return None
