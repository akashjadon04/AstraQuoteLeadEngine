#!/usr/bin/env python3
"""
render_start.py — Lightweight entrypoint for Render free tier (512MB RAM)
Only starts the Flask dashboard. Pipeline is triggered manually via the UI.
No heavy imports on boot = fits in 512MB.
"""

import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

os.makedirs("data", exist_ok=True)
os.makedirs("exports", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# Read PORT from env (Render injects this)
PORT = int(os.environ.get("PORT", 8800))

print(f"[AstraQuote] Starting dashboard on port {PORT}...")

# Init DB first (lightweight)
import config
from utils.database import init_db
init_db(config.DB_PATH)
print("[AstraQuote] Database ready.")

# Start Flask dashboard — single process, threaded
from dashboard.app import app
print(f"[AstraQuote] Dashboard live at http://0.0.0.0:{PORT}")
app.run(
    host="0.0.0.0",
    port=PORT,
    debug=False,
    use_reloader=False,
    threaded=True,
)
