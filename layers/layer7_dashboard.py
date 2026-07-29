# ============================================================
# layer7_dashboard.py — Dashboard Launcher
# Starts the Flask dashboard server and opens the browser
# ============================================================

import webbrowser
import threading
import time
import os
import sys

from rich.console import Console

import config
from utils.logger import get_logger

logger = get_logger("layer7")
console = Console()


def refresh_dashboard_data():
    """Refresh dashboard data from the database."""
    from utils.database import get_stats
    stats = get_stats()
    console.print(f"  Dashboard data: {stats.get('total', 0)} leads, "
                  f"{stats.get('enriched', 0)} enriched")


def launch_dashboard():
    """Launch the Flask dashboard server and open the browser."""
    refresh_dashboard_data()

    # Add project root to path so dashboard can find modules
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    def run_server():
        try:
            from dashboard.app import app
            app.run(
                host=config.DASHBOARD_HOST,
                port=config.DASHBOARD_PORT,
                debug=False,
                use_reloader=False,
            )
        except Exception as e:
            logger.error(f"Dashboard server error: {e}")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    time.sleep(2)

    console.print(f"\n  [bold green]✓ Dashboard running at {config.DASHBOARD_URL}[/bold green]")
    console.print("  [dim]Press Ctrl+C to stop[/dim]\n")

    webbrowser.open(config.DASHBOARD_URL)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")
