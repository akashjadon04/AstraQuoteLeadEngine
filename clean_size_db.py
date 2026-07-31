import sqlite3
import config

conn = sqlite3.connect('data/leads.db')
conn.row_factory = sqlite3.Row

# Demote sole_trader and micro leads to rejected
cursor = conn.execute(
    "UPDATE leads SET status = 'rejected', "
    "elimination_reasons = '[\"Eliminated: Company too small (sole trader / micro shop below minimum team size)\"]' "
    "WHERE status = 'enriched' AND size_band IN ('sole_trader', 'micro')"
)

conn.commit()

# Re-check stats
total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
qualified = conn.execute("SELECT COUNT(*) FROM leads WHERE status='enriched'").fetchone()[0]
by_size = dict(conn.execute("SELECT size_band, COUNT(*) FROM leads WHERE status='enriched' GROUP BY size_band").fetchall())
by_noga = dict(conn.execute("SELECT noga_code, COUNT(*) FROM leads WHERE status='enriched' GROUP BY noga_code").fetchall())

print(f"Strict Size Filter Applied to DB!")
print(f"Total leads in DB: {total}")
print(f"Delivered (enriched) team leads: {qualified}")
print(f"Size Band Breakdown: {by_size}")
print(f"NOGA Breakdown: {by_noga}")

conn.close()
