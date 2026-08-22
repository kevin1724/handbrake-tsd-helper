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
from copy import deepcopy

from .config import (
    PRESET_DIR,
    PRESET_CONFIG_FILE,
    DEFAULT_PRESET_CONFIG,
    QSV_1080_PRESET_CONFIG,
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

preset_config = deepcopy(DEFAULT_PRESET_CONFIG)


def _preset_rows(data) -> list[dict]:
    """Return selectable preset objects from supported HandBrake JSON shapes."""
    rows = []
    if isinstance(data, dict):
        if data.get("VideoEncoder") or data.get("PresetName") or data.get("Name"):
            rows.append(data)
        preset_list = data.get("PresetList")
        if isinstance(preset_list, list):
            rows.extend(row for row in preset_list if isinstance(row, dict))
    elif isinstance(data, list):
        rows.extend(row for row in data if isinstance(row, dict))
    return rows


def load_preset_definition(file_path: str, preset_name: str = "") -> dict:
    """Load the exact preset HandBrake will select from a preset JSON file."""
    with open(file_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    rows = _preset_rows(data)
    if not rows:
        raise ValueError(f"no HandBrake presets found in {file_path}")
    expected = str(preset_name or "").strip().casefold()
    if expected:
        selected = next(
            (
                row for row in rows
                if str(row.get("PresetName") or row.get("Name") or "").strip().casefold() == expected
            ),
            None,
        )
        if selected:
            return selected
    return rows[0]


def preset_mapping_issue(preset_key: str, file_path: str, preset_name: str = "") -> str:
    """Explain an obviously unsafe logical-to-HandBrake preset mapping."""
    key = str(preset_key or "").strip().lower()
    if key != "1080":
        return ""
    try:
        selected = load_preset_definition(file_path, preset_name)
    except Exception as exc:
        return f"preset could not be read ({exc})"

    actual_name = str(selected.get("PresetName") or selected.get("Name") or preset_name or "")
    description = str(selected.get("PresetDescription") or "")
    identity = f"{actual_name} {description}".casefold()
    try:
        width = int(selected.get("PictureWidth") or 0)
        height = int(selected.get("PictureHeight") or 0)
    except (TypeError, ValueError):
        width = height = 0
    if width > 1920 or height > 1080:
        return f"declares {width or '?'}x{height or '?'} dimensions"
    if ("4k" in identity or "2160" in identity or "uhd" in identity) and "1080" not in identity:
        return f"selects 4K preset {actual_name or os.path.basename(file_path)}"
    return ""


def _matching_1080_repair(file_path: str, preset_name: str = "") -> dict:
    """Keep the chosen encoder family while replacing a 4K-only 1080 map."""
    try:
        selected = load_preset_definition(file_path, preset_name)
        encoder = str(selected.get("VideoEncoder") or "").strip().lower()
    except Exception:
        encoder = ""
    if encoder.startswith("qsv_"):
        return deepcopy(QSV_1080_PRESET_CONFIG)
    return deepcopy(DEFAULT_PRESET_CONFIG["1080"])


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
        preset_config = deepcopy(DEFAULT_PRESET_CONFIG)
        return

    try:
        with open(PRESET_CONFIG_FILE, "r") as f:
            data = json.load(f)

        # Start from defaults, then overlay any user values
        cfg = deepcopy(DEFAULT_PRESET_CONFIG)

        for key in ("1080", "4k"):
            if key in data and isinstance(data[key], dict):
                # Use the user-selected file if provided, otherwise default.
                file_val = data[key].get("file") or cfg[key]["file"]
                requested_name = data[key].get("name") or cfg[key]["name"]
                # Resolve the name from the file itself so -Z, UI, and logs all
                # refer to the preset HandBrake actually imported.
                try:
                    selected = load_preset_definition(file_val, requested_name)
                    name_val = str(selected.get("PresetName") or selected.get("Name") or requested_name)
                except Exception:
                    name_val = requested_name
                cfg[key] = {"file": file_val, "name": name_val}

        issue = preset_mapping_issue(
            "1080",
            cfg["1080"]["file"],
            cfg["1080"].get("name") or "",
        )
        if issue:
            repaired = _matching_1080_repair(
                cfg["1080"]["file"],
                cfg["1080"].get("name") or "",
            )
            print(
                f"[WARN] Repaired invalid 1080p preset mapping: {issue}. "
                f"Using {repaired['name']}.",
                flush=True,
            )
            cfg["1080"] = repaired

        preset_config = cfg
        if issue:
            save_preset_config()

    except Exception as e:
        print(f"[WARN] Failed to load preset_config.json: {e}", flush=True)
        preset_config = deepcopy(DEFAULT_PRESET_CONFIG)


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
    preset_key = str(preset_key or "1080").strip().lower()
    if preset_key not in DEFAULT_PRESET_CONFIG:
        preset_key = "1080"

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
