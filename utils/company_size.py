# ============================================================
# company_size.py — Estimate how big a lead's business actually is
#
# THE HONEST CONSTRAINT: Switzerland publishes no employee headcount for
# SMEs in any free, automatable source (Zefix/SHAB carry legal form,
# officers and capital — never headcount; confirmed during the original
# build by testing real trade-company sites for self-published counts and
# finding effectively none). So we cannot know "this firm has 7 employees".
#
# What we CAN do is combine several public signals into a size BAND, each
# signal being a *lower bound* on size — so the estimate is the strongest
# evidence found (max of the signals), never an average that a single
# "Sàrl" could drag down. This is what stops one/two-person shops (which
# register as Sàrl exactly like a 15-person firm does) from being scored as
# mid-sized businesses.
#
# Pure function over already-collected fields — no network, safe to call
# anywhere in the pipeline or re-run standalone on existing data.
# ============================================================

import re
from typing import Any, Dict, List, Optional

import config

# Bands smallest → largest. Ranks live in config so the min-size gate is
# tunable there; mirrored here for local comparisons.
_BAND_RANK = config._SIZE_BAND_RANK
_ORDERED_BANDS = sorted(_BAND_RANK, key=lambda b: _BAND_RANK[b])

# Human-readable, explicitly-an-ESTIMATE headcount range per band.
_BAND_EMPLOYEES = {
    "sole_trader": "~1 (sole proprietor)",
    "micro": "~2-3 (est.)",
    "small": "~4-9 (est.)",
    "established": "~10+ (est.)",
    "unknown": "unknown",
}

# Fit-score contribution per band (0-30) — company size is AstraQuote's
# single most important ICP factor, so the spread is wide and the bottom
# bands score near zero.
_BAND_POINTS = {
    "established": 30,
    "small": 22,
    "micro": 8,
    "unknown": 6,
    "sole_trader": 0,
}

# Name morphology that implies more than one person (family firm, partnership,
# a group) — a genuine, if soft, staff signal.
_MULTI_PERSON_NAME_RE = re.compile(
    r"(&\s*fils|\bet\s+fils\b|&\s*cie|\bet\s+cie\b|fr[eè]res?|&\s*associ[eé]s?|"
    r"\bet\s+associ[eé]s?|p[eè]re\s+et\s+fils|\bgroupe?\b|\bgroup\b)",
    re.IGNORECASE,
)


def _band_from_rank(rank: int) -> str:
    for band in _ORDERED_BANDS:
        if _BAND_RANK[band] == rank:
            return band
    return "unknown"


def _max_band(a: str, b: str) -> str:
    """The larger of two bands. 'unknown' never wins against a real size band —
    real evidence always beats no evidence."""
    if a == "unknown":
        return b
    if b == "unknown":
        return a
    return a if _BAND_RANK[a] >= _BAND_RANK[b] else b


def _classify_legal_form(*texts: Optional[str]) -> str:
    """Map any legal-form text (name-derived label OR authoritative Zefix
    string) to a coarse class: 'sa', 'sarl', 'snc', 'raison_individuelle',
    'unknown'. Checks the most specific / largest forms first."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob.strip():
        return "unknown"
    if ("sa (" in blob or "société anonyme" in blob or "societe anonyme" in blob
            or "aktiengesellschaft" in blob or re.search(r"\bag\b", blob)
            or re.search(r"\bsa\b", blob)):
        return "sa"
    if ("sàrl" in blob or "sarl" in blob or "gmbh" in blob or "sagl" in blob
            or "responsabilité limitée" in blob or "responsabilite limitee" in blob):
        return "sarl"
    if "nom collectif" in blob or re.search(r"\bsnc\b", blob):
        return "snc"
    if ("raison individuelle" in blob or "entreprise individuelle" in blob
            or "einzelfirma" in blob or "einzelunternehmen" in blob):
        return "raison_individuelle"
    return "unknown"


def _band_from_headcount(n: int) -> str:
    if n >= 10:
        return "established"
    if n >= 4:
        return "small"
    if n >= 2:
        return "micro"
    return "sole_trader"


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def estimate_company_size(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate the lead's size band from every public signal already gathered.
    Returns {'band', 'employees_estimate', 'points', 'signals', 'passes_min'}.

    Each signal is treated as a lower bound; the result is the STRONGEST
    evidence found, so a real staff signal always lifts a business out of the
    'looks tiny' default and a bare sole-proprietorship with nothing to show
    stays at the bottom."""
    signals: List[str] = []

    # ── Base band from legal form ──────────────────────────────────────────
    form = _classify_legal_form(lead.get("zefix_legal_form"), lead.get("legal_form"))
    if form == "sa":
        band = "established"
        signals.append("SA/AG — CHF 100k+ registered capital, almost always multiple staff")
    elif form == "snc":
        band = "small"
        signals.append("SNC — a partnership, at least two associates by definition")
    elif form == "sarl":
        band = "micro"  # ambiguous on its own — needs corroboration to rise
        signals.append("Sàrl/GmbH — small team by default; looking for staff corroboration")
    elif form == "raison_individuelle":
        band = "sole_trader"
        signals.append("Registered as a sole proprietorship — structurally one person")
    else:
        band = "unknown"

    # ── A headcount the company publishes on its own site (strongest) ──────
    headcount = _to_int(lead.get("team_headcount_hint"))
    if headcount:
        hc_band = _band_from_headcount(headcount)
        band = _max_band(band, hc_band)
        signals.append(f"Site states ~{headcount} staff/collaborators")

    # ── Number of officers in the official SHAB gazette ───────────────────
    officers = _to_int(lead.get("officer_count"))
    if officers is not None:
        if officers >= 3:
            band = _max_band(band, "established")
            signals.append(f"{officers} officers registered in the SHAB gazette")
        elif officers == 2:
            band = _max_band(band, "small")
            signals.append("2 officers registered in the SHAB gazette")

    # ── Name morphology (& Fils, Frères, & Associés, Groupe…) ─────────────
    if _MULTI_PERSON_NAME_RE.search(lead.get("company_name") or ""):
        band = _max_band(band, "small")
        signals.append("Company name implies a family firm / partnership")

    # ── Website team signals ──────────────────────────────────────────────
    if lead.get("mentions_team"):
        band = _max_band(band, "small")
        signals.append("Website has a team / 'notre équipe' / collaborators section")
    dm_people = _to_int(lead.get("web_dm_candidate_count")) or 0
    if dm_people >= 3:
        band = _max_band(band, "small")
        signals.append(f"{dm_people} distinct people named on the site")

    if band == "unknown":
        signals.append("No size signal found either way")

    return {
        "band": band,
        "employees_estimate": _BAND_EMPLOYEES.get(band, "unknown"),
        "points": _BAND_POINTS.get(band, 6),
        "signals": signals,
        "passes_min": passes_min_size(band),
    }


def passes_min_size(band: str) -> bool:
    """Is this band big enough for the final delivered list, per config?
    An 'unknown' band is governed by config.UNKNOWN_PASSES (default False —
    if we can't evidence real staff, we don't deliver it)."""
    if band == "unknown":
        return bool(getattr(config, "UNKNOWN_PASSES", False))
    min_band = getattr(config, "MIN_COMPANY_SIZE_BAND", "small")
    return _BAND_RANK.get(band, 0) >= _BAND_RANK.get(min_band, 3)
