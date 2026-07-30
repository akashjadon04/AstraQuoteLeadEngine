#!/usr/bin/env python3
"""
sync_to_render.py — Push local leads DB to Render cloud dashboard
Run this after every local pipeline run to make results visible from any device.

Usage:
    python sync_to_render.py

The script reads RENDER_URL and SYNC_TOKEN from environment or uses defaults.
"""

import os
import sys
import requests

# ── Config ────────────────────────────────────────────────────────────────────
RENDER_URL   = os.environ.get("RENDER_URL",   "https://astraquoteleadengine.onrender.com")
SYNC_TOKEN   = os.environ.get("SYNC_TOKEN",   "astraquote-sync-2024")
LOCAL_DB     = os.environ.get("LOCAL_DB",     "data/leads.db")
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(LOCAL_DB):
        print(f"[ERROR] Local DB not found at {LOCAL_DB}")
        print("        Run the pipeline first: .\\venv\\Scripts\\python.exe main.py")
        sys.exit(1)

    size_kb = os.path.getsize(LOCAL_DB) / 1024
    print(f"[SYNC] Uploading {LOCAL_DB} ({size_kb:.1f} KB) -> {RENDER_URL}")

    with open(LOCAL_DB, "rb") as f:
        try:
            resp = requests.post(
                f"{RENDER_URL}/api/upload-db",
                headers={"X-Sync-Token": SYNC_TOKEN},
                files={"db": ("leads.db", f, "application/octet-stream")},
                timeout=60
            )
        except requests.exceptions.ConnectionError:
            print(f"[ERROR] Cannot reach {RENDER_URL} — is the Render service running?")
            sys.exit(1)

    if resp.status_code == 200:
        data = resp.json()
        print("[SYNC] SUCCESS!")
        print(f"       Total leads on Render: {data.get('total', '?')}")
        print(f"       Qualified leads:       {data.get('qualified', '?')}")
        print(f"       Live at: {RENDER_URL}")
    elif resp.status_code == 401:
        print("[ERROR] Unauthorized — SYNC_TOKEN mismatch. Check Render env vars.")
        sys.exit(1)
    else:
        print(f"[ERROR] Upload failed: {resp.status_code} — {resp.text[:200]}")
        sys.exit(1)

if __name__ == "__main__":
    main()
