# AstraQuote Lead Engine

**Enterprise-Grade B2B Lead Generation for Swiss Trade Businesses**
Discovers plumbing, HVAC, and sanitaire companies across French-speaking Switzerland,
deeply researches them with a rule-based public-info research engine (no AI/LLM —
pure logic over what's actually published), and presents 50 fully-qualified leads —
each guaranteed a valid phone, a real named contact, and completed research — with
pain-point analysis and personalized pitch strategies.

---

## How It Works

```
DuckDuckGo + local.ch/search.ch → Discover 210+ businesses
    → Region & Trade Filter (6 cantons, valid Swiss phone, trade niche)
    → Research + Enrich + Final Gate (adaptive loop — keeps re-crawling for
      more candidates until 50 have a phone + a named contact + completed
      research + a big-enough estimated company size, or the search space
      is exhausted)
    → Beautiful Flask Dashboard + PDF Export
```

---

## Quick Start

### Step 1 — Install
```
Double-click setup.bat
```
Or manually:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2 — Configure
Open `config.py` and verify:
- `TARGET_CANTONS` — Cantons to target
- `PRIMARY_NICHES` — Business types to search
- `DISCOVERY_TARGET` / `TARGET_LEAD_COUNT` — Pipeline sizing (defaults: 210 raw leads →
  50 final leads, each guaranteed a phone + named contact + completed research)

### Step 3 — Validate
```bash
python main.py --validate
```

### Step 4 — Run the Engine
```bash
python main.py
```

### Step 5 — View Results
Dashboard opens automatically at `http://localhost:8800`
Or manually: `python main.py --dashboard`

---

## Commands

| Command | What it does |
|---|---|
| `python main.py` | Full pipeline run |
| `python main.py --validate` | Check config is correct |
| `python main.py --dashboard` | Launch dashboard only |
| `python main.py --export` | Export leads to CSV/Excel |
| `python main.py --stats` | Show database statistics |
| `python main.py --rescore` | Recompute fit_score for existing leads after a `utils/scoring.py` change (instant, no network) |

---

## The Layers

| Layer | Name | Purpose |
|---|---|---|
| L1 | Discovery | Crawl 210+ businesses via DuckDuckGo and the local.ch directory |
| L2 | Filter | Region, phone, niche, size filtering |
| L3-L6 | Research, Enrich & Final Gate | **One adaptive loop, not four one-shot steps.** Researches and enriches candidates (website analysis, decision-maker search, AstraQuote Fit Score), then checks how many meet the hard bar — valid phone + named contact + completed research. Short of `TARGET_LEAD_COUNT` (default 50)? It re-crawls for more raw material (`layer4_recrawl.py`) and repeats, up to `MAX_RECRAWL_ITERATIONS`, until the target is met or the search space is genuinely exhausted. Only the best `TARGET_LEAD_COUNT` by fit score are delivered; everything else actually processed is kept as `status='rejected'` with a specific reason, never silently dropped. |
| L7 | Dashboard | Beautiful Flask UI + PDF export with Evolnex branding |

---

## Open Source Tools Used

| Tool | Purpose |
|---|---|
| `ddgs` | DuckDuckGo web search (discovery) |
| `httpx` | Async HTTP client (site crawling, directory scraping) |
| `beautifulsoup4` | HTML parsing (data extraction) |
| `phonenumbers` | Swiss phone number validation |
| `dnspython` | MX/A record checks for email discovery |

---

## Target Profile

- **Industries**: Plomberie, Chauffage/HVAC, Sanitaire, Climatisation, Ferblanterie
- **Cantons**: Genève, Fribourg, Valais, Vaud, Neuchâtel, Jura
- **Company size**: at least a real small team — one/two-person structures are
  filtered out (tunable via `MIN_COMPANY_SIZE_BAND`, default `"small"` ≈ 4+).
  Exact headcount isn't published for Swiss SMEs, so size is *estimated* from
  public signals (see below), not read from a field.
- **Must Have**: public phone number **and** a named decision-maker

---

## Research Engine

No external AI/LLM is used anywhere in the pipeline. Layer 5 is a deterministic,
rule-based agent: it crawls each lead's own website (homepage + contact/devis/
services/about subpages), and derives digital-maturity/urgency scores, pain
points, and a pitch/opening line entirely from what's actually publicly
observable — SSL, quote-form presence, social links, site freshness, public
reviews. Same inputs always produce the same output — nothing is guessed. The
lead's digital gap only picks which opening *hook* to use — the pitch itself
always sells AstraQuote's real product (an internal quoting tool for the
company's own staff), never "we'll build you a website."

Digital maturity/urgency are separate from **fit** — how well a business
actually matches AstraQuote's target customer. Layer 6 computes a 0-100
**AstraQuote Fit Score** (`utils/scoring.py`) from company size, verified
registration, niche, and — weighted just as heavily as size — whether a real
decision-maker was found, preferring manager titles (gérant/directeur/
responsable) over owner titles over a name merely inferred from the company
name. A lead with no named contact at all cannot qualify, no matter how good
everything else looks: you can't cold-call "the company," only a person. This
is the score the dashboard sorts by default and the one that determines
"qualified," not digital maturity.

### Company size — how it's estimated (and why it's an estimate)

Switzerland publishes **no employee headcount** for SMEs in any free,
automatable source (Zefix/SHAB carry legal form, officers and capital — never
headcount). So the engine can't read "7 employees" from a field — it would be
wrong to claim otherwise. Instead `utils/company_size.py` estimates a size
**band** from several public signals, each treated as a *lower bound* so the
strongest evidence wins (a lone "Sàrl" can't drag a real firm down):

1. **A headcount the company states on its own site** ("notre équipe de 12
   collaborateurs") — strongest; used directly.
2. **Number of officers registered in the SHAB gazette** — 2 → small team,
   3+ → established.
3. **Legal form** — SA/AG (CHF 100k+ capital) ≈ staffed; a bare sole
   proprietorship is one person by definition and is excluded.
4. **Company-name morphology** — "& Fils", "& Cie", "Frères", "& Associés",
   "Groupe" imply a real team.

Bands: `sole_trader` (~1) · `micro` (~2-3) · `small` (~4-9) · `established`
(~10+) · `unknown`. `MIN_COMPANY_SIZE_BAND` (default `"small"`) is the smallest
band allowed into the final 50 — this is what removes the one/two-person shops.
The adaptive loop keeps searching until 50 leads clear this bar (and the phone
+ contact + research bars) or the region is genuinely exhausted. Every lead's
size band and the exact evidence behind it are shown in the dashboard and PDF,
so a rep can see *why* a company is considered big enough.

---

## File Structure

```
AstraQuoteLeadEngine/
├── main.py                     ← Run this
├── config.py                   ← Your settings
├── setup.bat                   ← One-click install
├── requirements.txt
├── layers/
│   ├── layer1_discovery.py     ← Web crawling
│   ├── layer2_filter.py        ← Filtering
│   ├── layer3_gate.py          ← Data-completeness ranking helper
│   ├── layer4_recrawl.py       ← Re-crawl loop (called adaptively from main.py)
│   ├── layer5_research.py      ← Rule-based research
│   ├── layer6_enrich.py        ← Contact enrichment + Fit Score
│   └── layer7_dashboard.py     ← Dashboard launcher
├── utils/
│   ├── database.py             ← SQLite ORM
│   ├── scoring.py              ← AstraQuote Fit Score (ICP match)
│   ├── company_size.py         ← Multi-signal company-size estimate
│   ├── net.py                  ← Shared rate limiter / circuit breaker for DDGS + HTTP
│   ├── web_analyzer.py         ← Multi-page website analyzer (incl. staff signals)
│   ├── search_ch.py            ← local.ch / search.ch client
│   ├── state_manager.py        ← Pipeline state (atomic writes)
│   └── logger.py               ← Rich logger
├── dashboard/
│   ├── app.py                  ← Flask server
│   ├── pdf_generator.py        ← PDF export
│   ├── templates/              ← HTML templates
│   └── static/                 ← CSS + JS
├── data/
│   ├── leads.db                ← SQLite database
│   └── engine.log              ← Run logs
└── exports/                    ← CSV/Excel/PDF files
```

---

## Built by Evolnex.digital
