import json
from datetime import datetime
from html import escape as _esc

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except Exception as e:
    WEASYPRINT_AVAILABLE = False
    print(f"Warning: WeasyPrint not available (missing GTK dependencies): {e}")


# ============================================================
# Shared brand CSS — matches dashboard/static/style.css exactly
# (dark glassmorphism, purple/cyan Evolnex palette) so the
# exported report and the live dashboard feel like one product.
# ============================================================
_BRAND_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

:root {
    --bg-base: #040409;
    --bg-card: rgba(13, 13, 27, 0.75);
    --bg-card-hover: rgba(20, 20, 43, 0.9);
    --border-color: rgba(255, 255, 255, 0.08);
    --border-glow: rgba(139, 92, 246, 0.25);
    --primary: #8b5cf6;
    --accent: #06b6d4;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Plus Jakarta Sans', 'Segoe UI', sans-serif;
    background-color: var(--bg-base);
    background-image:
        radial-gradient(at 0% 0%, rgba(139, 92, 246, 0.10) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(6, 182, 212, 0.08) 0px, transparent 50%);
    color: var(--text-main);
    line-height: 1.5;
    padding: 2.5rem clamp(1rem, 5vw, 4rem);
    min-height: 100vh;
}
.report-header {
    display: flex; justify-content: space-between; align-items: flex-end;
    flex-wrap: wrap; gap: 1rem;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 1.5rem; margin-bottom: 2rem;
}
.brand {
    font-family: 'Outfit', sans-serif; font-size: 1.9rem; font-weight: 800;
    background: linear-gradient(135deg, #fff 30%, var(--primary) 70%, var(--accent) 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    letter-spacing: -0.02em;
}
.brand-sub { color: var(--text-muted); font-size: 0.85rem; margin-top: 0.2rem; }
.report-meta { text-align: right; color: var(--text-muted); font-size: 0.85rem; }
.report-meta strong { color: var(--text-main); }

.stat-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem; margin-bottom: 2rem;
}
.stat-card {
    background: var(--bg-card); border: 1px solid var(--border-color);
    border-radius: 1rem; padding: 1.25rem 1.5rem; backdrop-filter: blur(16px);
}
.stat-value {
    font-family: 'Outfit', sans-serif; font-size: 2rem; font-weight: 800; line-height: 1;
}
.stat-label { color: var(--text-muted); font-size: 0.8rem; margin-top: 0.4rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.stat-card.accent-primary .stat-value { color: var(--primary); }
.stat-card.accent-success .stat-value { color: var(--success); }
.stat-card.accent-cyan .stat-value { color: var(--accent); }

.methodology {
    background: rgba(139, 92, 246, 0.05); border: 1px solid var(--border-glow);
    border-radius: 1rem; padding: 1.25rem 1.5rem; margin-bottom: 2rem; font-size: 0.85rem; color: var(--text-muted);
}
.methodology strong { color: var(--text-main); }
.methodology .weights { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-top: 0.6rem; }
.methodology .weight-chip { color: var(--text-main); }
.methodology .weight-chip b { color: var(--accent); }

.controls {
    display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: center;
    margin-bottom: 1.5rem; position: sticky; top: 0; z-index: 10;
    background: rgba(4, 4, 9, 0.85); backdrop-filter: blur(12px);
    padding: 0.75rem 0; border-bottom: 1px solid var(--border-color);
}
.controls input, .controls select {
    background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); border-radius: 0.6rem;
    color: var(--text-main); padding: 0.55rem 0.9rem; font-family: inherit; font-size: 0.85rem;
}
.controls input:focus, .controls select:focus { outline: none; border-color: var(--primary); }
.controls label {
    display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: var(--text-muted);
    cursor: pointer; user-select: none;
}
.controls .result-count { margin-left: auto; color: var(--text-muted); font-size: 0.85rem; }
.sort-btn {
    background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); color: var(--text-muted);
    border-radius: 0.6rem; padding: 0.55rem 0.9rem; font-size: 0.8rem; cursor: pointer; font-weight: 600;
}
.sort-btn.active { color: var(--primary); border-color: var(--border-glow); }

.lead-card {
    background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 1rem;
    margin-bottom: 0.75rem; backdrop-filter: blur(16px); overflow: hidden;
    transition: border-color 0.2s;
}
.lead-card.qualified { border-left: 3px solid var(--success); }
.lead-card:not(.qualified) { border-left: 3px solid var(--border-color); }
.lead-card-head {
    display: flex; align-items: center; gap: 1rem; padding: 1rem 1.25rem; cursor: pointer;
}
.lead-card-head:hover { background: rgba(255,255,255,0.02); }
.fit-badge {
    font-family: 'Outfit', sans-serif; font-weight: 800; font-size: 1.05rem;
    width: 3rem; height: 3rem; border-radius: 0.75rem; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.fit-90 { background: rgba(16,185,129,0.15); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.3); }
.fit-75 { background: rgba(6,182,212,0.15); color: #67e8f9; border: 1px solid rgba(6,182,212,0.3); }
.fit-50 { background: rgba(245,158,11,0.15); color: #fde047; border: 1px solid rgba(245,158,11,0.3); }
.fit-0  { background: rgba(239,68,68,0.12); color: #fda4af; border: 1px solid rgba(239,68,68,0.25); }

.lead-main { flex: 1; min-width: 0; }
.lead-name { font-weight: 700; font-size: 1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lead-meta { color: var(--text-muted); font-size: 0.8rem; margin-top: 0.15rem; }
.lead-quick-contact { display: flex; gap: 0.6rem; align-items: center; flex-shrink: 0; }
.lead-quick-contact a {
    color: var(--text-main); text-decoration: none; font-size: 0.8rem;
    background: rgba(255,255,255,0.04); border: 1px solid var(--border-color);
    padding: 0.4rem 0.7rem; border-radius: 0.5rem; white-space: nowrap;
}
.lead-quick-contact a:hover { border-color: var(--primary); }
.pill { font-size: 0.7rem; font-weight: 700; padding: 0.25rem 0.6rem; border-radius: 1rem; white-space: nowrap; }
.pill-hot { background: rgba(239,68,68,0.15); color: #fda4af; }
.pill-warm { background: rgba(245,158,11,0.15); color: #fde047; }
.pill-cool { background: rgba(16,185,129,0.12); color: #6ee7b7; }
.expand-arrow { color: var(--text-muted); transition: transform 0.2s; flex-shrink: 0; }
.lead-card.open .expand-arrow { transform: rotate(180deg); }

.lead-card-body { display: none; padding: 0 1.25rem 1.25rem; border-top: 1px solid var(--border-color); }
.lead-card.open .lead-card-body { display: block; }
.detail-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.75rem; margin: 1rem 0;
}
.detail-item { font-size: 0.85rem; }
.detail-item .label { color: var(--text-muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; display: block; margin-bottom: 0.2rem; }
.score-breakdown { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.score-chip {
    font-size: 0.72rem; background: rgba(255,255,255,0.03); border: 1px solid var(--border-color);
    padding: 0.3rem 0.6rem; border-radius: 0.5rem; color: var(--text-muted);
}
.score-chip b { color: var(--text-main); }
.pain-list { margin: 0.5rem 0 0.75rem 1.1rem; font-size: 0.85rem; color: var(--text-muted); }
.pain-list li { margin-bottom: 0.3rem; }
.opening-box {
    background: rgba(0,0,0,0.35); border-left: 3px solid var(--primary); border-radius: 0.5rem;
    padding: 0.9rem 1rem; font-style: italic; font-size: 0.88rem; margin-top: 0.5rem; color: #e2e8f0;
}
.section-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent); font-weight: 700; margin-top: 1rem; display: block; }

.empty-state { text-align: center; color: var(--text-muted); padding: 3rem 1rem; }

@media print {
    body { background: #fff; color: #111; padding: 1cm; }
    .controls { display: none; }
    .lead-card { break-inside: avoid; border: 1px solid #ddd; background: #fff; }
    .lead-card-body { display: block !important; }
    .expand-arrow { display: none; }
    .stat-card, .methodology { background: #f8f8fb; border-color: #e5e7eb; }
    .lead-name, .stat-value, .brand { color: #111 !important; -webkit-text-fill-color: initial; }
}
"""


def _fit_bucket(score):
    if score is None:
        return "fit-0"
    if score >= 90:
        return "fit-90"
    if score >= 75:
        return "fit-75"
    if score >= 50:
        return "fit-50"
    return "fit-0"


def _urgency_pill(score):
    if score is None:
        return ""
    if score >= 8:
        return f'<span class="pill pill-hot">🔥 Urgency {score}/10</span>'
    if score >= 5:
        return f'<span class="pill pill-warm">Urgency {score}/10</span>'
    return f'<span class="pill pill-cool">Urgency {score}/10</span>'


def _parse_points(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [str(raw)]


def _parse_breakdown(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def generate_full_report(leads, output_path):
    """A real, organized, scannable report — sorted by AstraQuote fit score by
    default, qualified (>=75) leads visually distinguished, searchable/filterable/
    sortable in-browser, with each lead's scoring rationale and full pitch detail
    one click away. Falls back to this styled HTML directly when WeasyPrint isn't
    available (JS/interactivity won't survive a WeasyPrint render, since it's a
    static HTML-to-PDF renderer with no JS engine — but the content and layout
    still render fine as a flat document)."""
    from utils.scoring import QUALIFICATION_THRESHOLD

    enriched = []
    for lead in leads:
        fit_score = lead.get("fit_score")
        breakdown = _parse_breakdown(lead.get("fit_score_breakdown"))
        enriched.append({**lead, "_fit": fit_score if fit_score is not None else 0, "_breakdown": breakdown})

    enriched.sort(key=lambda l: l["_fit"], reverse=True)
    qualified_count = sum(1 for l in enriched if l["_fit"] >= QUALIFICATION_THRESHOLD)
    avg_fit = round(sum(l["_fit"] for l in enriched) / len(enriched)) if enriched else 0
    avg_urgency = round(sum((l.get("urgency_score") or 0) for l in enriched) / len(enriched), 1) if enriched else 0

    cards_html = []
    for lead in enriched:
        fit = lead["_fit"]
        bd = lead["_breakdown"]
        company = _esc(lead.get("company_name") or "Unknown")
        canton = _esc(lead.get("canton") or "-")
        niche = _esc(lead.get("niche") or "-")
        legal_form = _esc(lead.get("legal_form") or "-")
        phone = _esc(lead.get("phone") or "")
        email = _esc(lead.get("email") or "")
        website = _esc(lead.get("website") or "")
        dm = _esc(lead.get("decision_maker") or "")
        dm_title = _esc(lead.get("decision_title") or "")
        desc = _esc(lead.get("business_description") or "")
        opening = _esc(lead.get("custom_opening") or "")
        pitch = _esc(lead.get("pitch_angle") or "")
        pain_points = _parse_points(lead.get("pain_points"))
        qualified = fit >= QUALIFICATION_THRESHOLD

        contact_bits = []
        if phone:
            contact_bits.append(f'<a href="tel:{phone}">📞 {phone}</a>')
        if email:
            contact_bits.append(f'<a href="mailto:{email}">✉️ Email</a>')

        breakdown_chips = "".join(
            f'<span class="score-chip">{_esc(k.replace("_", " ").title())}: <b>{v}</b></span>'
            for k, v in bd.items()
        )
        pain_html = "".join(f"<li>{_esc(p)}</li>" for p in pain_points) or "<li>None identified</li>"

        cards_html.append(f"""
        <div class="lead-card {'qualified' if qualified else ''}" data-fit="{fit}" data-canton="{canton}" data-niche="{niche}" data-name="{company.lower()}">
            <div class="lead-card-head" onclick="this.parentElement.classList.toggle('open')">
                <div class="fit-badge {_fit_bucket(fit)}">{fit}</div>
                <div class="lead-main">
                    <div class="lead-name">{company}</div>
                    <div class="lead-meta">{canton} · {legal_form} · {niche}{' · ' + dm if dm else ''}</div>
                </div>
                <div class="lead-quick-contact">
                    {''.join(contact_bits)}
                    {_urgency_pill(lead.get('urgency_score'))}
                </div>
                <div class="expand-arrow">▾</div>
            </div>
            <div class="lead-card-body">
                <span class="section-label">Why this score</span>
                <div class="score-breakdown">{breakdown_chips}</div>

                <div class="detail-grid">
                    <div class="detail-item"><span class="label">Est. Company Size</span>{_esc(lead.get('employees_estimate') or 'unknown')}</div>
                    <div class="detail-item"><span class="label">Website</span>{f'<a href="{website}" style="color:var(--text-main)">{website}</a>' if website else '-'}</div>
                    <div class="detail-item"><span class="label">Decision Maker</span>{(dm + (f" — {dm_title}" if dm_title else "")) if dm else '⚠️ None found — verify before calling'}</div>
                    <div class="detail-item"><span class="label">Registry (Zefix)</span>{_esc(lead.get('zefix_uid') or 'Not verified')}</div>
                    <div class="detail-item"><span class="label">Activity</span>{desc or '-'}</div>
                </div>

                <span class="section-label">Pain Points</span>
                <ul class="pain-list">{pain_html}</ul>

                <span class="section-label">Pitch Angle</span>
                <p style="font-size:0.85rem;color:var(--text-muted);margin-top:0.3rem;">{pitch or '-'}</p>

                <span class="section-label">Suggested Opening</span>
                <div class="opening-box">"{opening or 'N/A'}"</div>
            </div>
        </div>
        """)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AstraQuote — Qualified Leads Report</title>
<style>{_BRAND_CSS}</style>
</head>
<body>
    <div class="report-header">
        <div>
            <div class="brand">AstraQuote</div>
            <div class="brand-sub">Qualified Leads Report · Built by Evolnex.digital</div>
        </div>
        <div class="report-meta">
            Generated <strong>{datetime.now().strftime('%d %B %Y, %H:%M')}</strong><br>
            {len(enriched)} leads processed
        </div>
    </div>

    <div class="stat-grid">
        <div class="stat-card accent-success"><div class="stat-value">{len(enriched)}</div><div class="stat-label">Delivered Leads (all verified)</div></div>
        <div class="stat-card accent-primary"><div class="stat-value">{avg_fit}</div><div class="stat-label">Average Fit Score</div></div>
        <div class="stat-card accent-cyan"><div class="stat-value">{avg_urgency}</div><div class="stat-label">Average Urgency /10</div></div>
        <div class="stat-card"><div class="stat-value">{qualified_count}</div><div class="stat-label">Top-Tier Fit (≥{QUALIFICATION_THRESHOLD})</div></div>
    </div>

    <div class="methodology">
        <strong>How the Fit Score works</strong> — built specifically for AstraQuote's target customer: a Swiss trade
        business with real staff, since the product is used by employees, not a single owner. A sole proprietorship
        can score well on everything else and still fail to qualify — that's intentional. A lead with no named
        contact also can't qualify, regardless of score: manager titles (gérant/directeur/responsable) score
        highest, an owner/associate next, a name only guessed from the company name lowest, and no name at all
        blocks qualification outright — you can't cold-call "the company," only a person.
        <div class="weights">
            <span class="weight-chip"><b>30pts</b> Company size (estimated band)</span>
            <span class="weight-chip"><b>15pts</b> Verified active registration</span>
            <span class="weight-chip"><b>15pts</b> Digital readiness to adopt software</span>
            <span class="weight-chip"><b>10pts</b> Core niche match</span>
            <span class="weight-chip"><b>30pts</b> Named decision-maker (manager preferred)</span>
        </div>
        <div style="margin-top:0.6rem;font-size:0.8rem;">Company size is <b>estimated</b> from public signals
        (published headcount, officers registered in the SHAB gazette, legal form, name) — exact headcount
        isn't published for Swiss SMEs. One/two-person structures are filtered out of this list; confirm team
        size on the call.</div>
    </div>

    <div class="controls">
        <input type="text" id="searchBox" placeholder="Search company name...">
        <select id="cantonFilter"><option value="">All Cantons</option></select>
        <label><input type="checkbox" id="qualifiedOnly"> Top-tier fit only (≥{QUALIFICATION_THRESHOLD}) — off by default, every lead here is already delivered/call-ready</label>
        <button class="sort-btn active" data-sort="fit" onclick="setSort('fit', this)">Sort: Fit Score</button>
        <button class="sort-btn" data-sort="urgency" onclick="setSort('urgency', this)">Sort: Urgency</button>
        <span class="result-count" id="resultCount"></span>
    </div>

    <div id="leadsContainer">
        {''.join(cards_html)}
    </div>
    <div class="empty-state" id="emptyState" style="display:none;">No leads match the current filters.</div>

<script>
(function() {{
    var cards = Array.prototype.slice.call(document.querySelectorAll('.lead-card'));
    var cantonSet = new Set();
    cards.forEach(function(c) {{ if (c.dataset.canton && c.dataset.canton !== '-') cantonSet.add(c.dataset.canton); }});
    var cantonSelect = document.getElementById('cantonFilter');
    Array.from(cantonSet).sort().forEach(function(c) {{
        var opt = document.createElement('option'); opt.value = c; opt.textContent = c;
        cantonSelect.appendChild(opt);
    }});

    var currentSort = 'fit';

    function applyFilters() {{
        var search = document.getElementById('searchBox').value.toLowerCase();
        var canton = cantonSelect.value;
        var qualifiedOnly = document.getElementById('qualifiedOnly').checked;
        var visible = 0;

        cards.sort(function(a, b) {{
            var av = currentSort === 'fit' ? parseInt(a.dataset.fit) : parseFloat(a.querySelector('.pill') ? a.querySelector('.pill').textContent.match(/[\\d.]+/)[0] : 0);
            var bv = currentSort === 'fit' ? parseInt(b.dataset.fit) : parseFloat(b.querySelector('.pill') ? b.querySelector('.pill').textContent.match(/[\\d.]+/)[0] : 0);
            return bv - av;
        }});
        var container = document.getElementById('leadsContainer');
        cards.forEach(function(c) {{ container.appendChild(c); }});

        cards.forEach(function(c) {{
            var matches = true;
            if (search && c.dataset.name.indexOf(search) === -1) matches = false;
            if (canton && c.dataset.canton !== canton) matches = false;
            if (qualifiedOnly && !c.classList.contains('qualified')) matches = false;
            c.style.display = matches ? '' : 'none';
            if (matches) visible++;
        }});
        document.getElementById('resultCount').textContent = visible + ' of ' + cards.length + ' shown';
        document.getElementById('emptyState').style.display = visible === 0 ? 'block' : 'none';
    }}

    window.setSort = function(key, btn) {{
        currentSort = key;
        document.querySelectorAll('.sort-btn').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
        applyFilters();
    }};

    document.getElementById('searchBox').addEventListener('input', applyFilters);
    cantonSelect.addEventListener('change', applyFilters);
    document.getElementById('qualifiedOnly').addEventListener('change', applyFilters);

    applyFilters();
}})();
</script>
</body>
</html>
"""

    if not WEASYPRINT_AVAILABLE:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return

    font_config = FontConfiguration()
    HTML(string=html_content).write_pdf(output_path, font_config=font_config)


def _or_na(value, default="N/A"):
    """Like dict.get(key, default), but also treats None/empty-string as missing —
    dict.get()'s default only kicks in for an absent key, not a NULL database value,
    which is why fields like LinkedIn used to render the literal text 'None'."""
    return value if value not in (None, "") else default


def _render_pain_points(raw):
    """pain_points is stored as a JSON array string; render it as a bullet list
    instead of dumping the raw '["...", "..."]' JSON text into the PDF."""
    items = _parse_points(raw)
    if not items:
        return "<p>N/A</p>"
    return "<ul>" + "".join(f"<li>{_esc(str(point))}</li>" for point in items) + "</ul>"


def generate_lead_card(lead, output_path):
    """Single-lead detail sheet, matching the full report's visual language."""
    fit = lead.get("fit_score") or 0
    breakdown = _parse_breakdown(lead.get("fit_score_breakdown"))
    urgency = lead.get("urgency_score", 0)

    breakdown_chips = "".join(
        f'<span class="score-chip">{_esc(k.replace("_", " ").title())}: <b>{v}</b></span>'
        for k, v in breakdown.items()
    )

    size_signals = _parse_points(lead.get("size_signals"))
    size_signals_html = "".join(f"<li>{_esc(str(s))}</li>" for s in size_signals) or "<li>No size signal recorded</li>"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(_or_na(lead.get('company_name'), 'Unknown'))} — AstraQuote Lead Card</title>
<style>{_BRAND_CSS}</style>
</head>
<body>
    <div class="report-header">
        <div>
            <div class="brand">{_esc(_or_na(lead.get('company_name'), 'Unknown'))}</div>
            <div class="brand-sub">{_esc(lead.get('canton') or '')} · {_esc(lead.get('legal_form') or '')}</div>
        </div>
        <div class="fit-badge {_fit_bucket(fit)}" style="width:4rem;height:4rem;font-size:1.4rem;">{fit}</div>
    </div>

    <div class="methodology">
        <span class="section-label" style="margin-top:0;">Fit Score Breakdown</span>
        <div class="score-breakdown">{breakdown_chips}</div>
    </div>

    <div class="lead-card open">
        <div class="lead-card-body" style="border-top:none; padding-top:1.25rem;">
            <span class="section-label" style="margin-top:0;">Contact</span>
            <div class="detail-grid">
                <div class="detail-item"><span class="label">Phone</span>{_esc(_or_na(lead.get('phone')))}</div>
                <div class="detail-item"><span class="label">Email</span>{_esc(_or_na(lead.get('email')))}</div>
                <div class="detail-item"><span class="label">Website</span>{_esc(_or_na(lead.get('website')))}</div>
                <div class="detail-item"><span class="label">Address</span>{_esc(_or_na(lead.get('address')))}</div>
            </div>

            <span class="section-label">Business</span>
            <div class="detail-grid">
                <div class="detail-item"><span class="label">Est. Company Size</span>{_esc(_or_na(lead.get('employees_estimate')))}</div>
                <div class="detail-item"><span class="label">Legal Form</span>{_esc(_or_na(lead.get('legal_form')))}</div>
                <div class="detail-item"><span class="label">Registry Status</span>{_esc(_or_na(lead.get('zefix_status')))}</div>
                <div class="detail-item"><span class="label">Swiss UID</span>{_esc(_or_na(lead.get('zefix_uid')))}</div>
                <div class="detail-item"><span class="label">Activity</span>{_esc(_or_na(lead.get('business_description')))}</div>
            </div>
            <span class="section-label">Size Evidence</span>
            <ul class="pain-list">{size_signals_html}</ul>
            <p style="font-size: 0.78em; color: var(--text-muted); margin-top: 8px;">
                Exact employee count isn't published anywhere free/public for Swiss SMEs — the size above is an
                estimate from public signals. Confirm team size on the call.
            </p>

            <span class="section-label">Decision Maker</span>
            <div class="detail-grid">
                <div class="detail-item"><span class="label">Name</span>{_esc(_or_na(lead.get('decision_maker_name'), '⚠️ None found — verify before calling'))}</div>
                <div class="detail-item"><span class="label">Title</span>{_esc(_or_na(lead.get('decision_maker_title')))}</div>
                <div class="detail-item"><span class="label">LinkedIn</span>{_esc(_or_na(lead.get('decision_maker_linkedin')))}</div>
            </div>

            <span class="section-label">Scores</span>
            <div class="score-breakdown">
                {_urgency_pill(urgency)}
                <span class="score-chip">Digital Maturity: <b>{_esc(str(_or_na(lead.get('digital_score'))))}/5</b></span>
                <span class="score-chip">Contact Score: <b>{_esc(str(_or_na(lead.get('contact_score'))))}%</b></span>
            </div>

            <span class="section-label">Pain Points</span>
            {_render_pain_points(lead.get('pain_points'))}

            <span class="section-label">Pitch Strategy</span>
            <p style="font-size:0.85rem;color:var(--text-muted);margin-top:0.3rem;">{_esc(_or_na(lead.get('pitch_strategy')))}</p>

            <span class="section-label">Suggested Opening</span>
            <div class="opening-box">"{_esc(_or_na(lead.get('custom_opening_line')))}"</div>
        </div>
    </div>
</body>
</html>
"""

    if not WEASYPRINT_AVAILABLE:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return

    font_config = FontConfiguration()
    HTML(string=html_content).write_pdf(output_path, font_config=font_config)
