import sqlite3
import json

conn = sqlite3.connect('data/leads.db')
conn.row_factory = sqlite3.Row

leads = conn.execute(
    "SELECT company_name, phone, decision_maker, fit_score, noga_code, size_band, employees_estimate, city, canton, website, email "
    "FROM leads WHERE status = 'enriched' ORDER BY fit_score DESC"
).fetchall()

for i, r in enumerate(leads, 1):
    print(f"{i}. {r['company_name']}")
    print(f"   Phone: {r['phone']}")
    print(f"   Contact: {r['decision_maker']}")
    print(f"   Fit Score: {r['fit_score']} / 100")
    print(f"   NOGA Code: {r['noga_code']} (Plomberie, Sanitaire & Chauffage)")
    print(f"   Team Size: {r['size_band']} ({r['employees_estimate']})")
    print(f"   Location: {r['city'] or 'N/A'}, Canton {r['canton'] or 'N/A'}")
    print(f"   Website: {r['website'] or 'N/A'}")
    print(f"   Email: {r['email'] or 'N/A'}")
    print("-" * 60)

conn.close()
