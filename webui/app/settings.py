"""
Settings handling for HandBrake TSD Helper.

This module manages user-tunable settings such as:
- HandBrake thread (CPU core) count
- CPU profile selection for ETA estimation
- (future) UI theme, etc.

Settings are stored as JSON on disk in settings.json.
"""

import json
import os

from .config import DATA_DIR, ROOTS
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

    # Poster metadata for the beta library page.
    # TMDb is free for non-commercial use with attribution; blank disables lookups.
    "tmdb_api_key": "",
    "tmdb_bearer_token": "",

    # Beta page folder mapping. These narrow Beta scans to the folders users care about.
    "beta_media_folders": {
        "movies": [],
        "shows": [],
    },

    # Beta incremental auto scan. The scan engine reuses the Beta cache and
    # only reparses files whose path, size, or modified time changed.
    "beta_auto_scan_enabled": False,
    "beta_auto_scan_interval_minutes": 30,
    "beta_auto_scan_skip_while_encoding": True,
    "beta_auto_scan_auto_queue_tracked": True,
    "beta_auto_scan_file_stability_enabled": True,
    "beta_auto_scan_file_stability_minutes": 10,
}

_settings_cache: dict | None = None


def _ensure_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    return {}


def _path_is_under_allowed_root(path: str) -> bool:
    if not path:
        return False
    try:
        real = os.path.realpath(path)
        for root_path, _label in ROOTS:
            root_real = os.path.realpath(root_path)
            try:
                if os.path.commonpath([real, root_real]) == root_real:
                    return True
            except ValueError:
                continue
    except Exception:
        return False
    return False


def _normalize_beta_folder_rows(rows, default_label: str) -> list[dict]:
    out = []
    seen = set()
    if not isinstance(rows, list):
        return out

    for row in rows:
        if isinstance(row, str):
            path = row
            label = ""
        elif isinstance(row, dict):
            path = row.get("path") or ""
            label = row.get("label") or ""
        else:
            continue

        path = str(path or "").strip()
        if not path or not _path_is_under_allowed_root(path):
            continue

        real_key = os.path.normcase(os.path.realpath(path))
        if real_key in seen:
            continue
        seen.add(real_key)

        label = str(label or "").strip()
        if not label:
            label = os.path.basename(path.rstrip("/\\")) or default_label

        out.append({"path": path, "label": label[:80]})
        if len(out) >= 50:
            break

    return out


def _normalize_beta_media_folders(value) -> dict:
    value = _ensure_dict(value)
    return {
        "movies": _normalize_beta_folder_rows(value.get("movies"), "Movies"),
        "shows": _normalize_beta_folder_rows(value.get("shows"), "Shows"),
    }


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
    merged["beta_media_folders"] = _normalize_beta_media_folders(merged.get("beta_media_folders"))
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
    # Poster metadata credentials
    # ------------------------------------------------------------------
    for key in ("tmdb_api_key", "tmdb_bearer_token"):
        value = new_values.get(key, base.get(key, ""))
        base[key] = str(value or "").strip()

    # ------------------------------------------------------------------
    # Beta media folder mapping
    # ------------------------------------------------------------------
    beta_media_folders = new_values.get(
        "beta_media_folders",
        base.get("beta_media_folders", DEFAULT_SETTINGS["beta_media_folders"]),
    )
    base["beta_media_folders"] = _normalize_beta_media_folders(beta_media_folders)

    # ------------------------------------------------------------------
    # Beta auto scan settings
    # ------------------------------------------------------------------
    base["beta_auto_scan_enabled"] = bool(
        new_values.get("beta_auto_scan_enabled", base.get("beta_auto_scan_enabled", False))
    )
    base["beta_auto_scan_skip_while_encoding"] = bool(
        new_values.get(
            "beta_auto_scan_skip_while_encoding",
            base.get("beta_auto_scan_skip_while_encoding", True),
        )
    )
    base["beta_auto_scan_auto_queue_tracked"] = bool(
        new_values.get(
            "beta_auto_scan_auto_queue_tracked",
            base.get("beta_auto_scan_auto_queue_tracked", True),
        )
    )
    base["beta_auto_scan_file_stability_enabled"] = bool(
        new_values.get(
            "beta_auto_scan_file_stability_enabled",
            base.get("beta_auto_scan_file_stability_enabled", True),
        )
    )

    try:
        interval = int(
            new_values.get(
                "beta_auto_scan_interval_minutes",
                base.get("beta_auto_scan_interval_minutes", 30),
            )
        )
    except (TypeError, ValueError):
        interval = 30
    base["beta_auto_scan_interval_minutes"] = max(5, min(1440, interval))

    try:
        stability_minutes = int(
            new_values.get(
                "beta_auto_scan_file_stability_minutes",
                base.get("beta_auto_scan_file_stability_minutes", 10),
            )
        )
    except (TypeError, ValueError):
        stability_minutes = 10
    base["beta_auto_scan_file_stability_minutes"] = max(1, min(240, stability_minutes))

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
