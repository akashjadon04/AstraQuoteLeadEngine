import sqlite3
from utils.noga import classify_noga, NOGA_432201, NOGA_432202
from utils.database import init_db

init_db('data/leads.db')

conn = sqlite3.connect('data/leads.db')
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT id, company_name, niche, raw_snippet, status FROM leads").fetchall()

kept = 0
demoted = 0

for r in rows:
    lead_id = r["id"]
    name = r["company_name"] or ""
    niche = r["niche"] or ""
    snippet = r["raw_snippet"] or ""
    status = r["status"]

    info = classify_noga(niche, f"{name} {snippet}")

    if info:
        code = info["code"]
        conn.execute("UPDATE leads SET noga_code = ? WHERE id = ?", (code, lead_id))
        if status == 'enriched':
            kept += 1
    else:
        # Demote to rejected
        conn.execute(
            "UPDATE leads SET status = 'rejected', "
            "elimination_reasons = '[\"Eliminated: Not NOGA 4322 (Plomberie/Chauffage/Sanitaire)\"]' "
            "WHERE id = ?", (lead_id,)
        )
        demoted += 1

conn.commit()

# Re-check stats
total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
qualified = conn.execute("SELECT COUNT(*) FROM leads WHERE status='enriched'").fetchone()[0]
rejected = conn.execute("SELECT COUNT(*) FROM leads WHERE status='rejected'").fetchone()[0]
by_noga = dict(conn.execute("SELECT noga_code, COUNT(*) FROM leads WHERE status='enriched' GROUP BY noga_code").fetchall())
by_niche = dict(conn.execute("SELECT niche, COUNT(*) FROM leads WHERE status='enriched' GROUP BY niche").fetchall())

print(f"Cleaned Database!")
print(f"Total leads in DB: {total}")
print(f"Delivered (enriched) NOGA 4322 leads: {qualified}")
print(f"Rejected / Demoted: {rejected}")
print(f"NOGA Breakdown: {by_noga}")
print(f"Niche Breakdown: {by_niche}")

conn.close()
