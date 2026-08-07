# ============================================================
# global_state_manager.py — Isolated State Management for Global Lead Engine
# Stores state in data/global_pipeline_state.json
# ============================================================

import json
import os
from datetime import datetime

STATE_FILE = "data/global_pipeline_state.json"

DEFAULT_STATE = {
    "status": "idle",
    "current_layer": 0,
    "current_layer_name": "Idle",
    "leads_discovered": 0,
    "leads_filtered": 0,
    "leads_qualified": 0,
    "leads_researched": 0,
    "leads_enriched": 0,
    "last_log": "Global Lead Engine ready.",
    "updated_at": "",
    "stop_requested": False,
    "target_lead_count": 100,
}


def get_global_state():
    if not os.path.exists(STATE_FILE):
        return DEFAULT_STATE.copy()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_STATE.copy()


def update_global_state(**kwargs):
    state = get_global_state()
    state.update(kwargs)
    state["updated_at"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return state


def reset_global_state(target_count: int = 100):
    state = DEFAULT_STATE.copy()
    state["target_lead_count"] = target_count
    state["updated_at"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return state
