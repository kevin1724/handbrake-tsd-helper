"""
Preset handling for HandBrake TSD Helper.

This module is responsible for:
- Scanning the preset directory for .json preset files
- Loading & saving the 1080p / 4K preset mapping (which file is used for each)
- Guessing which preset to use based on the filename (auto mode)
- Resolving:
    - HB_PRESET_FILE  (path to JSON)
    - HB_PRESET_NAME  (name inside JSON)
  for a given preset key ("1080" or "4k")
"""

import os
import json

from .config import (
    PRESET_DIR,
    PRESET_CONFIG_FILE,
    DEFAULT_PRESET_CONFIG,
)

# -------------------------------------------------------------------
# Global in-memory preset config
# This mirrors DEFAULT_PRESET_CONFIG + any overrides loaded from disk.
# Structure:
#   {
#     "1080": {"file": "/presets/some1080.json", "name": "Some 1080 Preset"},
#     "4k":   {"file": "/presets/some4k.json",   "name": "Some 4K Preset"},
#   }
# -------------------------------------------------------------------

preset_config = DEFAULT_PRESET_CONFIG.copy()


# -------------------------------------------------------------------
# Preset file discovery
# -------------------------------------------------------------------

def list_preset_files():
    """
    Scan PRESET_DIR and return a sorted list of full paths to .json preset files.

    This is used by the UI to populate the dropdowns where the user chooses
    which preset file should be used for 1080p and 4K jobs.

    Returns:
        List[str]: e.g. ["/presets/full1080.json", "/presets/4k.json", ...]
    """
    files = []
    try:
        if os.path.isdir(PRESET_DIR):
            for entry in os.listdir(PRESET_DIR):
                full = os.path.join(PRESET_DIR, entry)
                if os.path.isfile(full) and entry.lower().endswith(".json"):
                    files.append(full)
    except Exception as e:
        print(f"[WARN] Failed to list presets in {PRESET_DIR}: {e}", flush=True)

    files.sort()
    return files


# -------------------------------------------------------------------
# Preset config persistence (which file is used for 1080 vs 4k)
# -------------------------------------------------------------------

def load_preset_config():
    """
    Load user-selected preset mapping for 1080 / 4K from PRESET_CONFIG_FILE.

    If the file is missing or invalid, we fall back to DEFAULT_PRESET_CONFIG.

    This sets the global `preset_config` variable.
    """
    global preset_config

    # If no config file yet, just use the defaults.
    if not os.path.isfile(PRESET_CONFIG_FILE):
        preset_config = DEFAULT_PRESET_CONFIG.copy()
        return

    try:
        with open(PRESET_CONFIG_FILE, "r") as f:
            data = json.load(f)

        # Start from defaults, then overlay any user values
        cfg = DEFAULT_PRESET_CONFIG.copy()

        for key in ("1080", "4k"):
            if key in data and isinstance(data[key], dict):
                # Use the user-selected file if provided, otherwise default.
                file_val = data[key].get("file") or cfg[key]["file"]
                # Keep the "name" field from defaults as a human-readable fallback.
                name_val = cfg[key]["name"]
                cfg[key] = {"file": file_val, "name": name_val}

        preset_config = cfg

    except Exception as e:
        print(f"[WARN] Failed to load preset_config.json: {e}", flush=True)
        preset_config = DEFAULT_PRESET_CONFIG.copy()


def save_preset_config():
    """
    Persist current preset_config to PRESET_CONFIG_FILE on disk.

    We save both "file" and "name" even though the UI only edits the file path.
    """
    try:
        with open(PRESET_CONFIG_FILE, "w") as f:
            json.dump(preset_config, f)
    except Exception as e:
        print(f"[WARN] Failed to save preset_config.json: {e}", flush=True)


# -------------------------------------------------------------------
# Preset auto-detection based on filename
# -------------------------------------------------------------------

def guess_preset_from_filename(filename: str) -> str:
    """
    Guess whether a file should use the 1080 or 4K preset based on its name.

    We look for common patterns in the filename like "1080p", "2160p", "4k", "uhd".

    Args:
        filename (str): Base filename (e.g., "Movie.2160p.BluRay.mkv")

    Returns:
        str: "1080" or "4k"
    """
    lower = filename.lower()

    # Treat obvious 4K indicators as 4k jobs
    if "2160p" in lower or "4k" in lower or "uhd" in lower:
        return "4k"

    # Explicit 1080p tag
    if "1080p" in lower:
        return "1080"

    # Fallback default if no clear tag: treat as 1080
    return "1080"


# -------------------------------------------------------------------
# Resolve preset file + preset name (HB_PRESET_FILE + HB_PRESET_NAME)
# -------------------------------------------------------------------

def resolve_preset_file_and_name(preset_key: str):
    """
    Given a logical preset key ("1080" or "4k"), determine:

        - The JSON file path: HB_PRESET_FILE
        - The preset name inside that JSON: HB_PRESET_NAME

    We try to read the preset name from the JSON. If that fails, we fall back
    to the default "name" from DEFAULT_PRESET_CONFIG.

    Supported HandBrake JSON shapes:
      - A single preset object with keys:
            { "PresetName": "...", ... } or { "Name": "...", ... }
      - A dictionary with a "PresetList" array, where the first element is a preset:
            { "PresetList": [ { "PresetName": "...", ... }, ... ], ... }

    Args:
        preset_key (str): "1080" or "4k"

    Returns:
        tuple[str, str]: (file_path, preset_name)
    """
    # Get current config for this key; fall back to defaults if missing
    cfg = preset_config.get(preset_key) or DEFAULT_PRESET_CONFIG.get(preset_key)

    # If somehow no config for this key, fall back to 1080 defaults.
    if not cfg:
        cfg = DEFAULT_PRESET_CONFIG["1080"]

    file_path = cfg.get("file") or DEFAULT_PRESET_CONFIG[preset_key]["file"]
    preset_name = None

    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        # If the JSON is a single preset dict:
        if isinstance(data, dict):
            # Direct preset
            if "PresetName" in data:
                preset_name = data["PresetName"]
            elif "Name" in data:
                preset_name = data["Name"]

            # Or list-of-presets form: pick the first one
            elif "PresetList" in data and isinstance(data["PresetList"], list) and data["PresetList"]:
                first = data["PresetList"][0]
                if isinstance(first, dict):
                    preset_name = first.get("PresetName") or first.get("Name")

    except FileNotFoundError:
        print(f"[WARN] Preset file not found: {file_path}", flush=True)
    except json.JSONDecodeError as e:
        print(f"[WARN] Failed to parse preset JSON {file_path}: {e}", flush=True)
    except Exception as e:
        print(f"[WARN] Error reading preset file {file_path}: {e}", flush=True)

    # If we couldn't detect a name from JSON, fall back to our default label.
    if not preset_name:
        preset_name = DEFAULT_PRESET_CONFIG.get(
            preset_key, DEFAULT_PRESET_CONFIG["1080"]
        )["name"]

    return file_path, preset_name
