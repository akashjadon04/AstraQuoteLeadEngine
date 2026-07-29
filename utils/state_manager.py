# ============================================================
# state_manager.py — Pipeline State Tracker
# Saves the active pipeline execution state to JSON for UI
# ============================================================

import os
import json
from datetime import datetime

STATE_FILE = "data/pipeline_state.json"

def get_state() -> dict:
    """Read the current pipeline state."""
    if not os.path.exists(STATE_FILE):
        return {
            "status": "idle",
            "current_layer": 0,
            "current_layer_name": "Idle",
            "leads_discovered": 0,
            "leads_filtered": 0,
            "leads_qualified": 0,
            "leads_researched": 0,
            "leads_enriched": 0,
            "last_log": "Engine is ready.",
            "updated_at": datetime.now().isoformat()
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Fallback in case of concurrent reads/writes
        return {
            "status": "running",
            "current_layer": 1,
            "current_layer_name": "Discovery",
            "leads_discovered": 0,
            "leads_filtered": 0,
            "leads_qualified": 0,
            "leads_researched": 0,
            "leads_enriched": 0,
            "last_log": "Processing...",
            "updated_at": datetime.now().isoformat()
        }

def update_state(updates: dict) -> None:
    """Update pipeline state fields. Writes atomically (temp file + os.replace) so a
    concurrent read from the Flask dashboard thread can never see a torn/partial file."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state = get_state()
    state.update(updates)
    state["updated_at"] = datetime.now().isoformat()
    try:
        tmp_path = f"{STATE_FILE}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        pass

class PipelineCancelled(Exception):
    pass

def check_cancellation() -> None:
    """Check if the user has requested pipeline cancellation."""
    state = get_state()
    if state.get("stop_requested"):
        update_state({"status": "idle", "stop_requested": False, "last_log": "Pipeline stopped by user request."})
        raise PipelineCancelled("Pipeline stopped by user request.")
