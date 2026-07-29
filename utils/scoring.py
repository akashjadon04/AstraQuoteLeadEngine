# ============================================================
# scoring.py — AstraQuote Fit Score
# Answers a different question than urgency_score or contact_score:
# NOT "how complete is this lead's data" or "how should we open the
# call" — but "does this business actually match who buys and uses
# AstraQuote". AstraQuote is a quoting tool used BY EMPLOYEES, so a
# single-person sole-proprietorship is structurally a poor fit no
# matter how reachable or digitally savvy it is; a verified,
# actively-registered company with real staff is a good fit even if
# its website is dated.
#
# Contact quality is weighted just as heavily as company size: a
# lead nobody can put a name to isn't outreach-ready no matter how
# good it looks on paper ("who do I even ask for?"), so `qualified`
# is gated on having found a named person, not just on the point
# total. Manager titles (gérant/directeur/responsable) score
# highest, owner titles (propriétaire/administrateur/associé/...)
# next, a name inferred only from the company name lowest, and no
# name at all is a hard qualification blocker — see
# classify_contact_tier().
#
# Deliberately built from data already sitting in the DB — no new
# network calls, so it's instant and can be recomputed any time the
# rules change without re-running the pipeline.
# ============================================================

import json
from typing import Any, Dict

# Core = AstraQuote's direct quoting domain. Adjacent = related trades that still
# do complex on-site estimates and could plausibly buy, but aren't the primary target.
_CORE_NICHES = {"plomberie", "chauffage", "sanitaire", "climatisation", "installation"}
_ADJACENT_NICHES = {"ferblanterie"}

QUALIFICATION_THRESHOLD = 75

WEIGHTS = {
    "size": 30,
    "legitimacy": 15,
    "digital_readiness": 15,
    "niche": 10,
    "contact": 30,
}


def _size_score(lead: Dict[str, Any]) -> int:
    """The dominant factor: AstraQuote is used by employees, so company size
    matters more than almost anything else. When the company-size estimate has
    run (utils/company_size.py), score off its BAND — which fuses several
    signals (published headcount, registered officers, legal form, name) so a
    one-person Sàrl no longer scores like a real firm. Fall back to the old
    legal-form-only heuristic only when no band is present (e.g. rescoring rows
    written before size estimation existed)."""
    band = lead.get("size_band")
    if band:
        from utils.company_size import _BAND_POINTS
        return _BAND_POINTS.get(band, 6)

    # ── Legacy fallback: legal form only ──────────────────────────────────
    legal_form = (lead.get("legal_form") or "").lower()
    if "sa (" in legal_form or legal_form.startswith("ag ") or "aktiengesellschaft" in legal_form:
        return 30
    if "sàrl" in legal_form or "gmbh" in legal_form or "sagl" in legal_form:
        return 12  # was 19 — a bare Sàrl is no longer treated as a mid-sized firm on its own
    if "snc" in legal_form:
        return 12
    if "raison individuelle" in legal_form:
        return 0
    return 6  # legal form genuinely unknown


def _legitimacy_score(lead: Dict[str, Any]) -> int:
    """Confirmed against Switzerland's official commercial registry — not a
    scraped guess. An unconfirmed match scores 0, not a penalty: many tiny
    sole props are real but never appear in Zefix, so absence isn't proof of
    illegitimacy, just lower certainty."""
    if lead.get("zefix_uid"):
        if (lead.get("zefix_status") or "").upper() == "EXISTIEREND":
            return 15
        return 4  # matched a registry entry, but active status isn't confirmed
    return 0


def _digital_readiness_score(lead: Dict[str, Any]) -> int:
    """A real business can still be a poor SaaS prospect if there's no digital
    channel to sell, onboard, or support them through. This is about
    adoptability, not need — deliberately separate from urgency_score, which
    measures the opposite (how badly they need to modernize). Kept as a minor
    factor: AstraQuote is bought and used regardless of the buyer's own web
    presence, so this should never dominate the fit score."""
    score = 0
    if lead.get("has_website"):
        score += 6
    if lead.get("email"):
        score += 6
    if lead.get("has_quote_form") or lead.get("has_instagram") or lead.get("has_facebook") or lead.get("has_linkedin"):
        score += 3
    return score


def _niche_score(lead: Dict[str, Any]) -> int:
    niche = (lead.get("niche") or "").lower()
    if niche in _CORE_NICHES:
        return 10
    if niche in _ADJACENT_NICHES:
        return 5
    return 2


# ── Contact quality ──────────────────────────────────────────────────────
# Who we'd actually be calling matters as much as which company it is: a lead
# with no named contact isn't something a rep can cold-call with any
# credibility, so this is weighted on par with company size rather than as
# an afterthought (it used to be worth 5 of 100 points — now 30).
_MANAGER_TITLE_KEYWORDS = (
    "gérant", "gerant", "directeur", "directrice", "responsable",
    "chef d'entreprise", "geschäftsführer", "geschaftsfuhrer",
)
_OWNER_TITLE_KEYWORDS = (
    "propriétaire", "proprietaire", "fondateur", "fondatrice", "administrateur",
    "associé", "associe", "ceo", "patron", "titulaire", "président", "president",
)
_INFERRED_TITLE_MARKERS = ("probable", "déduit", "deduit")

CONTACT_TIER_POINTS = {"manager": 30, "owner": 22, "other": 16, "inferred": 12, "none": 0}
CONTACT_TIER_RANK = {"none": 0, "inferred": 1, "other": 2, "owner": 3, "manager": 4}


def classify_contact_tier(lead: Dict[str, Any]) -> str:
    """Classify the strength of the decision-maker contact found for this lead:
      'manager'  — gérant/directeur/responsable — the preferred contact, since
                   they run day-to-day operations and would actually use/approve AstraQuote.
      'owner'    — propriétaire/administrateur/associé/CEO/... — good, acceptable.
      'other'    — a real, verified name with no clean title match (e.g. a bare
                   LinkedIn hit) — still someone specific to ask for.
      'inferred' — only guessed from the company name itself (no independent
                   confirmation), e.g. "Propriétaire probable — déduit du nom".
      'none'     — no name found at all — not outreach-ready; you can't cold-call
                   "the company," only a person.
    """
    name = lead.get("decision_maker")
    if not name:
        return "none"
    title = (lead.get("decision_title") or "").lower()
    if any(marker in title for marker in _INFERRED_TITLE_MARKERS):
        return "inferred"
    if any(kw in title for kw in _MANAGER_TITLE_KEYWORDS):
        return "manager"
    if any(kw in title for kw in _OWNER_TITLE_KEYWORDS):
        return "owner"
    return "other"


# Marker embedded in layer6_enrich.py's _TITLE_SURNAME_GUESS — a BARE single
# word guessed from the company name ("Balmelli SA" -> "Balmelli"), with no
# first name and no independent confirmation. Live user review found this is
# genuinely too weak to call a "named contact": it's indistinguishable from a
# brand name that happens to look like a surname. A 2-3 token guess like
# "Bally Louis" (from "Bally Louis & Fils SA") reads as a real person and is
# NOT flagged by this — only the single-token case is this unreliable.
_WEAK_GUESS_MARKER = "nom de famille"


def is_weak_inferred_guess(lead: Dict[str, Any]) -> bool:
    """True only for the bare-surname-only mining guess — not for a full-name
    guess, a founding-partnership guess, or any independently verified contact."""
    title = (lead.get("decision_title") or "").lower()
    return _WEAK_GUESS_MARKER in title


def _contact_score(lead: Dict[str, Any]) -> int:
    return CONTACT_TIER_POINTS[classify_contact_tier(lead)]


def compute_fit_score(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {'score': 0-100, 'qualified': bool, 'breakdown': {...},
    'contact_tier': str}.
    Pure function over already-collected fields — no I/O, safe to call for
    every lead in the pipeline or re-run standalone on existing data.

    `qualified` requires BOTH a score >= QUALIFICATION_THRESHOLD and a named
    contact (any tier) — a lead that scores well on paper but that nobody can
    put a name to isn't actually ready for outreach. In practice the two
    conditions reinforce each other: size + legitimacy + digital_readiness +
    niche cap out at 70 points, so contact (worth 30) is required to reach
    the 75-point threshold at all — a lead with no named contact literally
    cannot out-score its way to "qualified"."""
    breakdown = {
        "size": _size_score(lead),
        "legitimacy": _legitimacy_score(lead),
        "digital_readiness": _digital_readiness_score(lead),
        "niche": _niche_score(lead),
        "contact": _contact_score(lead),
    }
    total = sum(breakdown.values())
    tier = classify_contact_tier(lead)
    qualified = total >= QUALIFICATION_THRESHOLD and tier != "none"
    return {
        "score": total,
        "qualified": qualified,
        "breakdown": breakdown,
        "contact_tier": tier,
    }


def fit_score_breakdown_json(lead: Dict[str, Any]) -> str:
    return json.dumps(compute_fit_score(lead)["breakdown"], ensure_ascii=False)
