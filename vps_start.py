#!/usr/bin/env python3
"""
vps_start.py — AstraQuote Lead Engine VPS Entrypoint
Runs the Flask dashboard permanently + the pipeline loop in parallel.
This is the CMD entrypoint for the VPS Docker container.
"""

import os
import sys
import time
import threading
import asyncio
import logging

# Ensure UTF-8 everywhere
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Make sure project root is in path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

os.makedirs("data", exist_ok=True)
os.makedirs("exports", exist_ok=True)
os.makedirs("logs", exist_ok=True)

import config
from utils.database import init_db
from utils.logger import get_logger

logger = get_logger("vps_start")

# ── 1. Init Database ──────────────────────────────────────────
init_db(config.DB_PATH)
logger.info("Database initialised.")

# ── 2. Start Flask Dashboard (background thread, always on) ──
def run_dashboard():
    """Run Flask dashboard server — never exits."""
    from dashboard.app import app
    logger.info(f"Dashboard starting on 0.0.0.0:{config.DASHBOARD_PORT}")
    app.run(
        host="0.0.0.0",
        port=config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )

dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
dashboard_thread.start()
logger.info("Dashboard thread started. Waiting for it to be ready...")
time.sleep(3)
logger.info(f"Dashboard should be live at http://0.0.0.0:{config.DASHBOARD_PORT}")

# ── 3. Run pipeline in a loop ────────────────────────────────
LOOP_INTERVAL_HOURS = 6  # re-run the full pipeline every 6 hours

def run_pipeline_loop():
    """Run the lead pipeline, then wait, then repeat forever."""
    while True:
        try:
            logger.info("=" * 60)
            logger.info("Starting pipeline run...")
            logger.info("=" * 60)

            # Import the pipeline runner from main.py
            from main import run_pipeline
            stats = asyncio.run(run_pipeline())
            logger.info(f"Pipeline complete. Stats: {stats}")

        except Exception as e:
            logger.error(f"Pipeline run failed: {e}", exc_info=True)
            logger.info("Will retry in 30 minutes...")
            time.sleep(30 * 60)
            continue

        wait_seconds = LOOP_INTERVAL_HOURS * 3600
        logger.info(f"Pipeline done. Waiting {LOOP_INTERVAL_HOURS}h before next run...")
        time.sleep(wait_seconds)

pipeline_thread = threading.Thread(target=run_pipeline_loop, daemon=True)
pipeline_thread.start()
logger.info("Pipeline loop thread started.")

# ── 4. Keep container alive ───────────────────────────────────
logger.info("VPS entrypoint running. Dashboard + pipeline both active.")
try:
    while True:
        time.sleep(60)
        # Log a heartbeat so the container isn't considered idle
        logger.debug("Heartbeat — VPS container alive.")
except KeyboardInterrupt:
    logger.info("VPS entrypoint stopped by keyboard interrupt.")
    sys.exit(0)
