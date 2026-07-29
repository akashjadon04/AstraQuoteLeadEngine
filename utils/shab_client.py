# ============================================================
# shab_client.py — Swiss Official Gazette (SHAB/FOSC) Officer Lookup
# Every SA/Sàrl/GmbH director appointment in Switzerland is legally
# published in the SHAB. Its API (shared amtsblattportal platform)
# is public: search publications by keyword + rubric HR, then fetch
# each publication's XML, whose <publicationText> holds person
# entries in the statutory format:
#   "Frossard, Martin, de Vollèges, à Sembrancher, associé et
#    président des gérants, avec signature individuelle"
# We parse those entries, track who was later removed ("radiée"),
# and return the best current officer. Identity is verified via the
# company UID embedded in the publication whenever the lead has a
# Zefix UID — no fuzzy-name risk.
#
# Coverage note: the online archive starts ~2018. Companies with no
# registry activity since then return nothing — that's expected, and
# the caller falls back to other sources.
# ============================================================

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from utils.logger import get_logger

logger = get_logger("SHAB")

_BASE_URL = "https://www.shab.ch/api/v1"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# One shared, connection-pooled client (httpx.Client is documented safe for
# concurrent use across threads) instead of a fresh one per lookup. Layer 5/6
# call this per-lead with up to config.RESEARCH_CONCURRENCY/ENRICH_CONCURRENCY
# leads in flight at once — that many simultaneous fresh clients each doing
# their own DNS resolution is what produced live "getaddrinfo failed" bursts
# under load.
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
    r"\b(S\.?A\.?|S\.?à\.?r\.?l\.?|Sarl|Sagl|AG|GmbH|SNC|&\s?Cie|&\s?Fils|et\s?Cie)\b\.?,?\s*",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)

# Section headers in publication texts. French and German (our cantons publish in both).
_REMOVED_HEADER_RE = re.compile(
    r"(?:Personne\(s\)\s+et\s+signature\(s\)\s+radiée\(s\)|signature\(s\)\s+radiée\(s\)|"
    r"Personne\(s\)\s+radiée\(s\)|Ausgeschiedene\s+Personen|Gelöschte\s+Personen[^:]*)\s*:",
    re.IGNORECASE,
)
_PRESENT_HEADER_RE = re.compile(
    r"(?:Nouvelle\(s\)\s+personne\(s\)\s+inscrite\(s\)|Personne\(s\)\s+inscrite\(s\)|"
    r"Inscription\s+ou\s+modification\s+de\s+personne\(s\)|Modification(?:\(s\))?\s+de\s+personne\(s\)[^:]*|"
    r"Eingetragene\s+Personen|Geänderte\s+Personen[^:]*)\s*:",
    re.IGNORECASE,
)

_ROLE_SCORES: List[Tuple[re.Pattern, int]] = [
    (re.compile(r"associé[e]?[^.;]*gérant", re.IGNORECASE), 100),
    (re.compile(r"Gesellschafter(?:in)?[^.;]*Geschäftsführer", re.IGNORECASE), 100),
    (re.compile(r"président[e]?[^.;]*gérant", re.IGNORECASE), 96),
    (re.compile(r"administrateur(?:trice)?\s+unique", re.IGNORECASE), 95),
    (re.compile(r"gérant[e]?s?", re.IGNORECASE), 90),
    (re.compile(r"Geschäftsführer(?:in)?", re.IGNORECASE), 90),
    (re.compile(r"titulaire|Inhaber(?:in)?", re.IGNORECASE), 88),
    (re.compile(r"administrateur(?:trice)?[^.;]*président", re.IGNORECASE), 93),
    (re.compile(r"Mitglied[^.;]*Präsident", re.IGNORECASE), 93),
    (re.compile(r"administrateur(?:trice)?", re.IGNORECASE), 85),
    (re.compile(r"président[e]?", re.IGNORECASE), 84),
    (re.compile(r"Präsident(?:in)?", re.IGNORECASE), 84),
    (re.compile(r"Verwaltungsrat", re.IGNORECASE), 80),
    (re.compile(r"directeur|directrice|Direktor(?:in)?", re.IGNORECASE), 70),
    (re.compile(r"membre|Mitglied", re.IGNORECASE), 60),
]

_ENTRY_SKIP_RE = re.compile(
    r"organe\s+de\s+révision|office\s+de\s+révision|Revisionsstelle|Fiduciaire|"
    r"\bSA\b|\bSàrl\b|\bAG\b|\bGmbH\b",
    re.IGNORECASE,
)
_NAME_PART_RE = re.compile(r"^[A-ZÀ-Ý][\w'’ .-]{0,39}$")

_last_call = 0.0
_MIN_INTERVAL = 0.8


def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _tokens(name: str) -> set:
    return {w.lower() for w in _WORD_RE.findall(name) if len(w) > 2}


def _score_role(role_text: str) -> int:
    for pattern, score in _ROLE_SCORES:
        if pattern.search(role_text):
            bonus = 5 if re.search(r"individuelle|Einzelunterschrift", role_text, re.IGNORECASE) else 0
            return score + bonus
    return 0


def _parse_person_entries(section_text: str) -> List[Dict[str, str]]:
    """Parse 'Surname, Firstname, <origin/domicile parts>, role[, signature]' entries."""
    persons = []
    # Entries are sentences; a new entry starts with "Name," after a period.
    entries = re.split(r"\.\s+(?=[A-ZÀ-Ý][\w'’-]+,\s)", section_text)
    for entry in entries:
        entry = entry.strip().rstrip(".")
        if not entry or _ENTRY_SKIP_RE.search(entry.split(",")[0] if "," in entry else entry):
            continue
        parts = [p.strip() for p in entry.split(",")]
        if len(parts) < 4:
            continue
        surname, firstname = parts[0], parts[1]
        if not _NAME_PART_RE.match(surname) or not _NAME_PART_RE.match(firstname):
            continue
        if any(ch.isdigit() for ch in surname + firstname):
            continue
        rest = ", ".join(parts[2:])
        role_score = _score_role(rest)
        if role_score == 0:
            continue
        role_part = next((p for p in parts[2:] if _score_role(p) > 0), rest[:80])
        persons.append({
            "surname": surname,
            "firstname": firstname,
            "role": role_part,
            "score": role_score,
        })
    return persons


def _parse_publication_text(text: str) -> Tuple[List[Dict[str, str]], List[Tuple[str, str]]]:
    """Split a publication text into present/removed person lists."""
    present: List[Dict[str, str]] = []
    removed: List[Tuple[str, str]] = []

    # Build an ordered list of (position, kind) section markers.
    markers = [(m.start(), m.end(), "removed") for m in _REMOVED_HEADER_RE.finditer(text)]
    markers += [(m.start(), m.end(), "present") for m in _PRESENT_HEADER_RE.finditer(text)]
    markers.sort()

    for i, (start, end, kind) in enumerate(markers):
        section_end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        section = text[end:section_end]
        for person in _parse_person_entries(section):
            if kind == "removed":
                removed.append((person["surname"].lower(), person["firstname"].lower()))
            else:
                present.append(person)

    return present, removed


def find_officer(company_name: str, zefix_uid: str = "", timeout: float = 10.0,
                  max_publications: int = 4) -> Optional[Dict[str, Any]]:
    """Find the current top officer (gérant/administrateur/titulaire...) for a company
    from its official SHAB registry publications. Returns
    {'name', 'title', 'officer_count'} or None. `officer_count` is the number of
    distinct current (present-minus-removed) officers seen across the fetched
    publications — a registry-grade lower bound on company size (see
    utils/company_size.py). Never raises; bounded by per-request timeouts and a
    publication fetch cap."""
    if not company_name:
        return None

    query = _SUFFIX_RE.sub(" ", company_name)
    query = re.sub(r"\s+", " ", query).strip(" -–,")
    if not query:
        return None

    uid_digits = _digits(zefix_uid)
    company_tokens = _tokens(company_name)

    try:
        _rate_limit()
        client = _get_client()
        resp = client.get(
            f"{_BASE_URL}/publications",
            params={"publicationStates": "PUBLISHED", "keyword": query,
                    "rubrics": "HR", "pageRequest.size": 8},
            headers=_HEADERS,
        )
        if resp.status_code != 200:
            return None
        pubs = resp.json().get("content", [])
        if not pubs:
            return None

        # Newest first.
        pubs.sort(key=lambda p: p.get("meta", {}).get("publicationDate", ""), reverse=True)

        removed_set: set = set()
        candidates: List[Dict[str, Any]] = []
        fetched = 0

        for pub in pubs:
            if fetched >= max_publications:
                break
            meta = pub.get("meta", {})

            # Identity check before spending a fetch: UID when we have one,
            # title-token overlap otherwise.
            meta_uids = [_digits(u) for u in (meta.get("uid") or [])]
            if uid_digits:
                if meta_uids and uid_digits not in meta_uids:
                    continue
            else:
                title = (meta.get("title", {}) or {}).get("fr") or (meta.get("title", {}) or {}).get("de") or ""
                title_tokens = _tokens(title)
                if company_tokens and len(company_tokens & title_tokens) / len(company_tokens) < 0.6:
                    continue

            _rate_limit()
            xml_resp = client.get(f"{_BASE_URL}/publications/{meta['id']}/xml", headers=_HEADERS)
            fetched += 1
            if xml_resp.status_code != 200:
                continue

            text_match = re.search(r"<publicationText>(.*?)</publicationText>", xml_resp.text, re.S)
            if not text_match:
                continue
            pub_text = re.sub(r"<[^>]+>", " ", text_match.group(1))
            pub_text = re.sub(r"\s+", " ", pub_text)

            # Final identity guard: the statutory text always embeds the UID.
            if uid_digits and uid_digits not in _digits(pub_text):
                continue

            present, removed = _parse_publication_text(pub_text)
            for person in present:
                key = (person["surname"].lower(), person["firstname"].lower())
                if key in removed_set:
                    continue
                candidates.append(person)
            removed_set.update(removed)

        if not candidates:
            return None

        # Highest role score wins; earlier (newer publication) wins ties.
        best_by_person: Dict[tuple, Dict[str, Any]] = {}
        for person in candidates:
            key = (person["surname"].lower(), person["firstname"].lower())
            if key not in best_by_person or person["score"] > best_by_person[key]["score"]:
                best_by_person[key] = person

        best = max(best_by_person.values(), key=lambda p: p["score"])
        return {
            "name": f"{best['firstname']} {best['surname']}",
            "title": best["role"],
            # Distinct current officers (already de-duped by (surname, firstname)
            # in best_by_person, with removed persons filtered out above) — a
            # lower bound on how many people run/own the company.
            "officer_count": len(best_by_person),
        }
    except Exception as e:
        logger.debug(f"SHAB officer lookup failed for '{company_name}': {e}")
        return None
