# AstraQuote Lead Engine Documentation

## Overview
AstraQuote Lead Engine is a fully automated pipeline designed to discover, qualify,
enrich, and research plumbing and heating businesses in Switzerland. The goal is to
generate highly qualified leads that are prime candidates for the AstraQuote AI
quoting agent. The engine itself uses **no external AI/LLM** — every scoring and
text-generation step is deterministic logic applied to publicly available data
(the lead's own website, directory listings, public reviews).

## The Layer Architecture

The engine operates through a series of layers, progressively refining and
enriching the lead data. Layers 1, 2, and 7 are strictly sequential one-shot
steps; Layers 3-6 form a single **adaptive research/enrich/final-gate loop**
(see below) rather than four independent passes, because research and
enrichment have real attrition — not every candidate yields a discoverable
contact, and not every site analysis completes before its timeout — so
processing a fixed batch once would deliver fewer than `TARGET_LEAD_COUNT`
usable leads. Clicking **START** in the dashboard calls `/api/pipeline/start`,
which spawns the pipeline in a background thread; every layer reports
progress into `utils/state_manager.py` so the dashboard can poll it in real
time.

### Layer 1: Discovery (`layers/layer1_discovery.py`)
- **Objective:** Find a large pool of initial prospects.
- **Methods:** DuckDuckGo search (`ddgs`, via the shared rate-limited `utils/net.py`
  gate) and the local.ch business directory (`utils/search_ch.py`) across the
  target Swiss cantons.
- **Target:** Collects up to `DISCOVERY_TARGET` (default: 210) raw leads before
  proceeding, split across DDGS/directory/Maps sources with early-exit once each
  source's soft cap is reached.
- **Tagging:** Each query carries the canton/city it targets, so results are
  tagged from known query context rather than guessed from snippet text.
- **Deduplication:** Removes duplicates by phone number (or normalized company
  name when no phone was found) and skips any number already in the blacklist.

### Layer 2: Region & Size Filter (`layers/layer2_filter.py`)
- **Objective:** Clean out irrelevant or unusable leads.
- **Methods:**
  - Validates and formats phone numbers to Swiss E.164 (`phonenumbers`) — leads
    without a valid Swiss number are eliminated.
  - Eliminates leads whose detected canton isn't in `TARGET_CANTONS`.
  - Eliminates leads matching `EXCLUDE_KEYWORDS` (e.g. marketing agencies).
  - Eliminates leads with no trade-relevant keyword match.

### Layers 3-6: Research, Enrich & Final Gate (orchestrated in `main.py`'s `run_pipeline()`)
- **Objective:** Deliver exactly `TARGET_LEAD_COUNT` (default: 50) leads that
  each have a valid phone, a real named contact, completed research, **and an
  estimated company size big enough to be worth calling** — not just
  `TARGET_LEAD_COUNT` candidates that merely passed Layer 2.
- **Methods:**
  1. Every Layer-2-passed candidate is ranked by a data-completeness score
     (phone/website/email/niche — `layers/layer3_gate.py`'s `select_top`) so
     the most promising candidates in a batch are the ones concurrency slots
     pick up first, then run through Layer 5 (research) and Layer 6
     (enrichment) below.
  2. After each batch, a lead counts toward the target only if it clears
     **all four** hard requirements: valid phone, a named decision-maker
     (any contact tier — see Layer 6), `research_complete = True` (i.e. Layer 5
     finished normally rather than hitting its timeout/crash fallback), and a
     company-size band ≥ `MIN_COMPANY_SIZE_BAND` (default `"small"`). The size
     band is estimated by `utils/company_size.py` from public signals
     (self-published headcount, officers registered in the SHAB gazette, legal
     form, and name morphology) — Switzerland doesn't publish exact SME
     headcount anywhere free, so this is an evidence-based estimate, not a read
     value, and it exists specifically to keep one/two-person structures out of
     the delivered list.
  3. If fewer than `TARGET_LEAD_COUNT` leads clear the bar, **Layer 4
     (`layers/layer4_recrawl.py`)** expands the search — secondary niches
     (iteration 1), all cities per canton (iteration 2), broader terms +
     LinkedIn (iteration 3+) — for a fresh batch of raw candidates, which are
     filtered (Layer 2) and run through the same research → enrich → check
     cycle. This repeats until the target is met or `MAX_RECRAWL_ITERATIONS`
     (default: 20) is hit, deduplicating against every candidate already
     seen and tagging canton/city from query context exactly like Layer 1.
  4. If the search space is exhausted (a re-crawl iteration turns up no new
     candidates at all) before the target is reached, the pipeline stops
     early and reports honestly how many final leads it actually found,
     rather than padding the count with leads that don't meet the bar.
  5. Once enough candidates clear the bar, only the best `TARGET_LEAD_COUNT`
     **by AstraQuote Fit Score** (see Layer 6) are kept as the delivered set.
     Every other candidate that was actually processed — no contact found,
     research incomplete, or simply out-scored — is kept in the database
     with `status='rejected'` and a specific reason, never silently dropped.

### Layer 5: Deep Research (`layers/layer5_research.py`)
- **Objective:** Understand the business and craft a personalized sales pitch —
  entirely from public information, no AI.
- **Methods:**
  - Crawls the lead's own website (homepage + contact/devis/services/about
    subpages, via `utils/web_analyzer.py`) for SSL, quote-form presence, social
    links, tech stack, meta description, site freshness (copyright year),
    decision-maker candidate text blocks, and **staff-size signals** (a
    self-published headcount like "12 collaborateurs", and team/collaborators
    section mentions — feeds the company-size estimate).
  - Optionally (capped, circuit-breaker protected) checks public Google reviews
    for rating/review-count/slow-response signals.
  - Computes a **digital maturity score (1-5)** and an **urgency score (1-10)**
    from those signals with a fixed formula (lower digital maturity → higher
    urgency), generates a rule-based **pain-points list**, and picks a
    **pitch angle + custom opening line** from a template keyed to the lead's
    single biggest digital gap (no website / no quote form / outdated site / no
    social). That gap only changes which *hook* opens the conversation — every
    template's substance is AstraQuote's actual product (an internal tool the
    company's own staff use to build a quote in minutes and track it through to
    invoice), never "let us build/fix your website." Digital maturity and
    urgency describe how receptive a pitch angle might land, not whether the
    business is a good AstraQuote customer — that's a separate axis, see the
    **AstraQuote Fit Score** under Layer 6 below.
  - Hard-capped at `LEAD_RESEARCH_TIMEOUT` per lead so one slow site can never
    stall the batch.

### Layer 6: Contact Enrichment (`layers/layer6_enrich.py`)
- **Objective:** Find out exactly who to contact.
- **Methods:**
  - Re-validates the phone number and detects mobile vs. landline.
  - Discovers a likely email from the site's domain (MX/A record check).
  - Finds the decision-maker by trying up to four sources, in decreasing order
    of authority — but unlike a simple waterfall, it doesn't stop at the first
    source that returns *any* name. It keeps trying sources until a
    **manager-tier** contact is found (gérant/directeur/responsable — the
    person who actually runs day-to-day operations and would use/approve
    AstraQuote) or every source is exhausted, always keeping whichever
    candidate found so far ranks highest:
    1. The company's own about/team/impressum page (scraped once in Layer 5).
    2. **SHAB** (`utils/shab_client.py`) — Switzerland's official gazette, where
       every registered officer appointment is legally published. Returns the
       registered officer's full name and legal role (gérant, administrateur,
       titulaire...), identity-verified via the company's Zefix UID, with
       removed-officer ("radiée") tracking so ex-directors are never returned.
       Online archive covers ~2018 onward.
    3. Mining the company name itself — Swiss trade businesses are very often
       named after their owner ("Portier Eric SA", "Dalloyeau Sàrl",
       "Décotterd & Bulliard"). Guarded by trade/place/marketing stop-lists and
       always labeled as inferred ("déduit du nom de l'entreprise").
    4. A capped DuckDuckGo LinkedIn search, only accepted when the result
       verifiably mentions the company.
  - Every candidate found (from any source) is classified into a contact tier
    by `utils/scoring.classify_contact_tier`: **manager** (gérant/directeur/
    responsable — preferred) > **owner** (propriétaire/administrateur/
    associé/CEO/...) > **other** (a real name, role unconfirmed) > **inferred**
    (guessed from the company name only) > **none**. A lead in the "none" tier
    — no name found anywhere — cannot be outreach-ready no matter how good it
    looks otherwise; see the Fit Score below.
  - When a name is found, the cold-call opening line is personalized with it
    ("Bonjour, je cherche à joindre …"), stating the role out loud too for
    confirmed (non-guessed) manager/owner-tier contacts.
  - Adds every finalized lead's phone number to the blacklist so it's never
    re-scraped or re-contacted in a future run.
  - **Company-size estimate** (`utils/company_size.py`): before scoring, fuses
    the officer count returned by the SHAB lookup with the website staff signals
    from Layer 5, the legal form, and the company name into a size *band*
    (`sole_trader`/`micro`/`small`/`established`/`unknown`) plus the human
    evidence behind it. Each signal is a lower bound, so the strongest evidence
    wins — a one-person Sàrl no longer looks like a real firm.
  - **AstraQuote Fit Score** (`utils/scoring.py`, computed last since it needs
    everything gathered above): a 0-100 ICP-match score answering "does this
    business match who actually buys and uses AstraQuote" — company size via the
    estimated band (30pts), verified active registration (15pts), digital
    readiness to adopt software (15pts), core niche match (10pts), and named
    contact tier (30pts). This is **deliberately separate** from
    `digital_maturity`/`urgency_score` above (those describe the business's
    own web presence and pitch-angle framing, not lead quality) and is the
    score the dashboard sorts by default. A lead only counts as `qualified`
    when the score clears 75 **and** a named contact was found — a high score
    with no contact tier above "none" is explicitly blocked, since a lead
    nobody can put a name to isn't actually ready for a cold call.

### Layer 7: Dashboard Generation (`layers/layer7_dashboard.py` / `dashboard/app.py`)
- **Objective:** Present the enriched data beautifully.
- **Methods:** Finalizes all data into the local SQLite database
  (`data/leads.db`), then launches/refreshes the Flask dashboard — filtering,
  sorting, charts, and CSV/Excel/PDF export via `/api/export/*`.

## Configuration (`config.py`)
- `DISCOVERY_TARGET` (default 210) — raw leads targeted in Layer 1.
- `TARGET_LEAD_COUNT` (default 50) — the FINAL, fully-qualified count the
  Layers 3-6 loop guarantees (phone + named contact + completed research),
  not a pre-research candidate cap.
- `MAX_RECRAWL_ITERATIONS` (default 20) — cap on how many times the Layers
  3-6 loop will re-crawl for more raw material before giving up and
  reporting an honest shortfall.
- `MIN_COMPANY_SIZE_BAND` (default `"small"`) — the smallest estimated size
  band (`sole_trader` < `micro` < `small` < `established`) allowed into the
  final delivered set. `"small"` excludes one/two-person structures; loosen to
  `"micro"` if strict filtering can't find enough leads, tighten to
  `"established"` to only ever call sizeable firms.
- `UNKNOWN_PASSES` (default `False`) — whether a lead whose size couldn't be
  estimated at all is given the benefit of the doubt. Default strict: if we
  can't evidence real staff, it isn't delivered.
- `RESEARCH_CONCURRENCY` / `ENRICH_CONCURRENCY` — parallelism for Layers 5/6.
- `LEAD_RESEARCH_TIMEOUT` / `LEAD_ENRICH_TIMEOUT` — per-lead hard time ceilings.
- `ENABLE_REVIEW_SEARCH` / `ENABLE_DM_SEARCH_FALLBACK` — toggle the optional
  capped DDGS lookups in Layers 5/6.
- `NET_*` — global DDGS rate limit, timeout, and circuit-breaker tuning
  (`utils/net.py`), shared by every layer so no single layer can hammer
  DuckDuckGo into blocking the whole run.

## How to Run
```bash
python main.py
```
To view the dashboard only (using existing data):
```bash
python main.py --dashboard
```
Other flags: `--validate` (check config), `--export` (CSV/Excel), `--stats`
(database summary), `--rescore` (recompute `fit_score` for existing leads
after a `utils/scoring.py` change — instant, no network calls, does not
re-run decision-maker discovery itself).
