import sqlite3
import sys

# Force UTF-8 output
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import config
from layers.layer2_filter import batch_filter
from utils.database import export_leads_csv, export_leads_excel

def clean_database():
    conn = sqlite3.connect("data/leads.db")
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute("SELECT * FROM leads").fetchall()
    leads = [dict(r) for r in rows]
    print(f"Total leads before cleanup: {len(leads)}")
    
    passed, eliminated = batch_filter(leads)
    print(f"Passed clean plumber filter: {len(passed)}")
    print(f"Eliminated noise leads: {len(eliminated)}")
    
    # Delete eliminated noise leads from the database
    eliminated_phones = [l["phone"] for l in eliminated if l.get("phone")]
    if eliminated_phones:
        placeholders = ",".join("?" for _ in eliminated_phones)
        conn.execute(f"DELETE FROM leads WHERE phone IN ({placeholders})", eliminated_phones)
        conn.commit()
        print(f"Successfully purged {len(eliminated_phones)} non-plumbing/garbage entries from DB.")
    
    conn.close()
    
    # Re-export clean CSV and Excel
    export_leads_csv("exports/clean_plumber_leads.csv", include_all=True)
    export_leads_excel("exports/clean_plumber_leads.xlsx", include_all=True)
    print("Exported clean files to exports/clean_plumber_leads.xlsx and exports/clean_plumber_leads.csv")

if __name__ == "__main__":
    clean_database()
