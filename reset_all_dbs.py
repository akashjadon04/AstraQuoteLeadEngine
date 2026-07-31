# reset_all_dbs.py — Complete Database Reset for Fresh Lead Engine Runs
import os
import shutil
import sqlite3
from utils.database import init_db, init_master_db, _db_path, _master_db_path

def reset_everything():
    print("Resetting all databases for a fresh run...")
    
    # 1. Remove database files if present
    for db_file in [_db_path, _master_db_path]:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
                print(f"Removed {db_file}")
            except Exception as e:
                print(f"Could not remove {db_file}: {e}")

    # 2. Remove backups directory if present
    backup_dir = "data/backups"
    if os.path.exists(backup_dir):
        try:
            shutil.rmtree(backup_dir)
            print("Cleared data/backups/")
        except Exception as e:
            print(f"Could not clear backups: {e}")

    # 3. Re-initialize empty databases with schema
    init_db()
    init_master_db()
    print("Successfully initialized clean data/leads.db and data/qualified_master.db!")

if __name__ == "__main__":
    reset_everything()
