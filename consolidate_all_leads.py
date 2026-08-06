import sqlite3
import os
import re
from utils.database import init_db

db_files = [
    "data/qualified_master.db",
    "data/backups/leads_before_run_20260806_072043.db",
    "data/backups/leads_before_run_20260805_225141.db",
    "data/leads.db"
]

all_candidates = []

for db_path in db_files:
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM leads").fetchall()
            for r in rows:
                all_candidates.append(dict(r))
            conn.close()
        except Exception as e:
            print(f"Error reading {db_path}: {e}")

print(f"Total raw candidate entries collected: {len(all_candidates)}")

# Filter and deduplicate
seen_keys = set()
qualified_leads = []

for lead in all_candidates:
    phone = lead.get("phone")
    dm = lead.get("decision_maker") or lead.get("decision_maker_name")
    comp = lead.get("company_name", "")
    
    # Must have phone and non-empty decision maker
    if not phone or not dm or str(dm).strip() == "" or str(dm).lower() in ("none", "null", "unknown"):
        continue
        
    # Deduplication key
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', comp.lower())
    key = clean_name or phone
    
    if key in seen_keys:
        continue
        
    seen_keys.add(key)
    lead["status"] = "enriched"
    lead["decision_maker"] = dm
    qualified_leads.append(lead)

print(f"Total deduplicated qualified leads with phone & decision maker: {len(qualified_leads)}")

# Write to data/leads.db and data/qualified_master.db
for target_db in ["data/leads.db", "data/qualified_master.db"]:
    init_db(target_db)
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    
    conn.execute("DELETE FROM leads")
    
    cols = [c[1] for c in conn.execute("PRAGMA table_info(leads)").fetchall()]
    
    for lead in qualified_leads:
        val_map = {}
        for c in cols:
            val_map[c] = lead.get(c, None)
        
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        query = f"INSERT OR REPLACE INTO leads ({col_names}) VALUES ({placeholders})"
        conn.execute(query, [val_map[c] for c in cols])
        
    conn.commit()
    conn.close()

print(f"Successfully updated data/leads.db and data/qualified_master.db with {len(qualified_leads)} qualified leads!")
