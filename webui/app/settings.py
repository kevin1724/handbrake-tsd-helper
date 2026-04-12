"""
Settings handling for HandBrake TSD Helper.

This module manages user-tunable settings such as:
- HandBrake thread (CPU core) count
- CPU profile selection for ETA estimation
- (future) UI theme, etc.

Settings are stored as JSON on disk in settings.json.
"""

import json

from .config import DATA_DIR
from .cpu_profiles import CPU_PROFILES  # NEW

# Where settings are stored on disk (inside /app/data by default)
SETTINGS_FILE = (DATA_DIR.rstrip("/") + "/settings.json")

# Default values for all settings
DEFAULT_SETTINGS = {
    # HandBrake threads (0 = auto / HandBrake default)
    "hb_threads": 0,

    # Size Wizard / ETA estimation
    "cpu_profile": "i5-9500t",      # baseline CPU
    "cpu_speed_override": 1.0,       # multiplier (1.0 = no adjustment)

    # Queue UI behavior on the Jobs page
    # buttons = classic button controls
    # drag_drop = grab rows and reorder visually
    "queue_ui_mode": "buttons",
}

_settings_cache: dict | None = None


def _ensure_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    return {}


def load_settings() -> dict:
    """Load settings from disk (with in-memory caching)."""
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except Exception as e:  # just logging
        print(f"[WARN] Failed to load settings.json: {e}", flush=True)
        data = {}

    data = _ensure_dict(data)
    merged = DEFAULT_SETTINGS.copy()
    merged.update(data)
    _settings_cache = merged
    return merged


def save_settings(new_values: dict) -> dict:
    """Merge and persist settings to disk, returning the updated dict."""
    global _settings_cache
    base = load_settings().copy()
    new_values = _ensure_dict(new_values)

    # ------------------------------------------------------------------
    # HandBrake threads
    # ------------------------------------------------------------------
    hb_threads = new_values.get("hb_threads", base.get("hb_threads", 0))
    try:
        hb_threads_int = int(hb_threads)
    except (TypeError, ValueError):
        hb_threads_int = 0
    if hb_threads_int < 0:
        hb_threads_int = 0

    base["hb_threads"] = hb_threads_int

    # ------------------------------------------------------------------
    # CPU profile (Size Wizard ETA)
    # ------------------------------------------------------------------
    cpu_profile = new_values.get("cpu_profile", base.get("cpu_profile"))
    if isinstance(cpu_profile, str):
        cpu_profile = cpu_profile.strip().lower()
    else:
        cpu_profile = None

    if cpu_profile not in CPU_PROFILES:
        cpu_profile = DEFAULT_SETTINGS["cpu_profile"]

    base["cpu_profile"] = cpu_profile

    # ------------------------------------------------------------------
    # CPU speed override multiplier
    # ------------------------------------------------------------------
    cpu_speed_override = new_values.get(
        "cpu_speed_override",
        base.get("cpu_speed_override", 1.0),
    )
    try:
        cpu_speed_override = float(cpu_speed_override)
    except (TypeError, ValueError):
        cpu_speed_override = 1.0

    # sanity clamp
    if cpu_speed_override <= 0:
        cpu_speed_override = 1.0

    base["cpu_speed_override"] = cpu_speed_override

    # ------------------------------------------------------------------
    # Queue UI mode
    # ------------------------------------------------------------------
    queue_ui_mode = new_values.get("queue_ui_mode", base.get("queue_ui_mode", "buttons"))
    if isinstance(queue_ui_mode, str):
        queue_ui_mode = queue_ui_mode.strip().lower()
    else:
        queue_ui_mode = "buttons"
    if queue_ui_mode not in {"buttons", "drag_drop"}:
        queue_ui_mode = "buttons"
    base["queue_ui_mode"] = queue_ui_mode

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    _settings_cache = base
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(base, f, indent=2)
    except Exception as e:  # just logging
        print(f"[WARN] Failed to save settings.json: {e}", flush=True)

    return base
