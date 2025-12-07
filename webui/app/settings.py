"""
Settings handling for HandBrake TSD Helper.

This module manages user-tunable settings such as:
- HandBrake thread (CPU core) count
- (future) UI theme, etc.

Settings are stored as JSON on disk in settings.json.
"""

import json

from .config import DATA_DIR

# Where settings are stored on disk (inside /app/data by default)
SETTINGS_FILE = (DATA_DIR.rstrip("/") + "/settings.json")

# Default values for all settings
DEFAULT_SETTINGS = {
    # HandBrake threads (0 = auto / HandBrake default)
    "hb_threads": 0,
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

    # Normalize hb_threads
    hb_threads = new_values.get("hb_threads", base.get("hb_threads", 0))
    try:
        hb_threads_int = int(hb_threads)
    except (TypeError, ValueError):
        hb_threads_int = 0
    if hb_threads_int < 0:
        hb_threads_int = 0

    base["hb_threads"] = hb_threads_int

    _settings_cache = base
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(base, f, indent=2)
    except Exception as e:  # just logging
        print(f"[WARN] Failed to save settings.json: {e}", flush=True)

    return base
