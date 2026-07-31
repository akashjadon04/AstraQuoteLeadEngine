import sqlite3
from utils.noga import classify_noga, NOGA_4322, NOGA_4322A, NOGA_4322B
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
        code = info["sub_code"]  # 43.22A or 43.22B
        conn.execute("UPDATE leads SET noga_code = ? WHERE id = ?", (code, lead_id))
        if status == 'enriched':
            kept += 1
    else:
        # Demote to rejected
        conn.execute(
            "UPDATE leads SET status = 'rejected', "
            "elimination_reasons = '[\"Eliminated: Not NOGA 43.22 (Plomberie/Chauffage/Sanitaire)\"]' "
            "WHERE id = ?", (lead_id,)
        )
        demoted += 1

conn.commit()

# Re-check stats
total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
qualified = conn.execute("SELECT COUNT(*) FROM leads WHERE status='enriched'").fetchone()[0]
rejected = conn.execute("SELECT COUNT(*) FROM leads WHERE status='rejected'").fetchone()[0]
by_noga = dict(conn.execute("SELECT noga_code, COUNT(*) FROM leads WHERE status='enriched' GROUP BY noga_code").fetchall())

print("Cleaned Database with NOGA 43.22 Standard!")
print(f"Total leads in DB: {total}")
print(f"Delivered (enriched) NOGA 43.22 leads: {qualified}")
print(f"Rejected / Demoted: {rejected}")
print(f"NOGA Breakdown: {by_noga}")

conn.close()
