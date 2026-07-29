import os
import sqlite3
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "leads.db")

def generate_static_html():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM leads WHERE status != 'rejected' ORDER BY fit_score DESC").fetchall()
    conn.close()
    
    leads = [dict(r) for r in rows]
    leads_json = json.dumps(leads, ensure_ascii=False)
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AstraQuote — Swiss Trade B2B Leads</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding-bottom: 50px; }}
        .header-card {{ background: linear-gradient(135deg, #1e293b, #334155); border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #475569; }}
        .lead-card {{ background: #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 16px; border: 1px solid #334155; transition: transform 0.2s; }}
        .lead-card:hover {{ transform: translateY(-2px); border-color: #3b82f6; }}
        .badge-fit {{ background: #22c55e; color: #fff; font-weight: 600; font-size: 0.9rem; padding: 6px 12px; border-radius: 20px; }}
        .badge-phone {{ background: #0284c7; color: #fff; text-decoration: none; padding: 6px 12px; border-radius: 20px; font-weight: 600; display: inline-block; }}
        .badge-phone:hover {{ background: #0369a1; color: #fff; }}
        .search-box {{ background: #0f172a; border: 1px solid #475569; color: #fff; padding: 12px; border-radius: 8px; width: 100%; }}
        .search-box:focus {{ background: #0f172a; color: #fff; border-color: #3b82f6; outline: none; }}
        .filter-select {{ background: #0f172a; border: 1px solid #475569; color: #fff; padding: 12px; border-radius: 8px; width: 100%; }}
    </style>
</head>
<body>
    <div class="container mt-4">
        <div class="header-card">
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-3">
                <div>
                    <h2 class="fw-bold mb-1">🚰 AstraQuote Swiss Trade Leads</h2>
                    <p class="text-secondary mb-0">Verified Plumbing, HVAC, & Sanitaire B2B Leads in Romandie</p>
                </div>
                <div>
                    <button onclick="exportCSV()" class="btn btn-primary fw-bold me-2">📄 Export CSV</button>
                    <button onclick="exportJSON()" class="btn btn-outline-light fw-bold">📥 Export JSON</button>
                </div>
            </div>
        </div>

        <div class="row g-3 mb-4">
            <div class="col-md-5">
                <input type="text" id="searchInput" onkeyup="filterLeads()" class="search-box" placeholder="Search company, contact, or phone...">
            </div>
            <div class="col-md-35 col-md-3">
                <select id="cantonFilter" onchange="filterLeads()" class="filter-select">
                    <option value="">All Cantons</option>
                    <option value="Genève">Genève</option>
                    <option value="Vaud">Vaud</option>
                    <option value="Valais">Valais</option>
                    <option value="Neuchâtel">Neuchâtel</option>
                    <option value="Jura">Jura</option>
                </select>
            </div>
            <div class="col-md-4">
                <select id="nicheFilter" onchange="filterLeads()" class="filter-select">
                    <option value="">All Niches</option>
                    <option value="plomberie">Plomberie</option>
                    <option value="chauffage">Chauffage</option>
                    <option value="sanitaire">Sanitaire</option>
                    <option value="climatisation">Climatisation</option>
                </select>
            </div>
        </div>

        <div id="statsSummary" class="mb-3 text-secondary"></div>

        <div id="leadsList"></div>
    </div>

    <script>
        const leadsData = {leads_json};

        function renderLeads(leads) {{
            const container = document.getElementById('leadsList');
            document.getElementById('statsSummary').innerText = `Showing ${{leads.length}} qualified Swiss leads`;
            
            if (leads.length === 0) {{
                container.innerHTML = '<div class="alert alert-warning">No leads match the selected filters.</div>';
                return;
            }}

            container.innerHTML = leads.map(l => `
                <div class="lead-card">
                    <div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                        <div>
                            <h4 class="fw-bold mb-1">${{l.company_name || 'Business'}}</h4>
                            <span class="badge bg-secondary me-1">${{l.niche || 'Trade'}}</span>
                            <span class="badge bg-outline-info me-1">${{l.canton || 'CH'}}</span>
                            <span class="badge bg-dark">${{l.size_band || 'small'}}</span>
                        </div>
                        <div>
                            <span class="badge-fit">Fit Score: ${{l.fit_score || 0}}/100</span>
                        </div>
                    </div>
                    <div class="row text-secondary mt-3">
                        <div class="col-md-4">
                            <strong>👤 Decision Maker:</strong> ${{l.decision_maker || 'N/A'}} (${{l.decision_title || 'Owner'}})
                        </div>
                        <div class="col-md-4">
                            <strong>📞 Phone:</strong> <a href="tel:${{l.phone}}" class="badge-phone">${{l.phone || 'N/A'}}</a>
                        </div>
                        <div class="col-md-4">
                            <strong>🌐 Website:</strong> ${{l.website ? `<a href="${{l.website}}" target="_blank" class="text-info">${{l.website}}</a>` : 'N/A'}}
                        </div>
                    </div>
                </div>
            `).join('');
        }}

        function filterLeads() {{
            const q = document.getElementById('searchInput').value.toLowerCase();
            const canton = document.getElementById('cantonFilter').value;
            const niche = document.getElementById('nicheFilter').value.toLowerCase();

            const filtered = leadsData.filter(l => {{
                const matchQ = !q || (l.company_name && l.company_name.toLowerCase().includes(q)) || 
                                     (l.decision_maker && l.decision_maker.toLowerCase().includes(q)) || 
                                     (l.phone && l.phone.includes(q));
                const matchCanton = !canton || l.canton === canton;
                const matchNiche = !niche || (l.niche && l.niche.toLowerCase().includes(niche));
                return matchQ && matchCanton && matchNiche;
            }});

            renderLeads(filtered);
        }}

        function exportCSV() {{
            if (!leadsData.length) return;
            const keys = Object.keys(leadsData[0]);
            let csv = keys.join(',') + '\\n';
            leadsData.forEach(row => {{
                csv += keys.map(k => `"${{(row[k] || '').toString().replace(/"/g, '""')}}"`).join(',') + '\\n';
            }});
            downloadFile(csv, 'astraquote_swiss_leads.csv', 'text/csv');
        }}

        function exportJSON() {{
            downloadFile(JSON.stringify(leadsData, null, 2), 'astraquote_swiss_leads.json', 'application/json');
        }}

        function downloadFile(content, fileName, contentType) {{
            const a = document.createElement('a');
            const file = new Blob([content], {{ type: contentType }});
            a.href = URL.createObjectURL(file);
            a.download = fileName;
            a.click();
        }}

        renderLeads(leadsData);
    </script>
</body>
</html>"""
    
    with open(os.path.join(os.path.dirname(__file__), "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("Generated static index.html with leads dataset.")

if __name__ == "__main__":
    generate_static_html()
