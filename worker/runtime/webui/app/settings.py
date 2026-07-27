"""Encoding-only durable settings for the headless worker.

Controller job payloads carry the effective thread and output-size safety
policy. These local defaults support older controllers and worker restarts.
"""

from __future__ import annotations

import json
import os
import shutil
import threading

from .config import DATA_DIR


SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SETTINGS_LOCK = threading.RLock()
DEFAULT_SETTINGS = {
    "hb_threads": 0,
    "auto_stop_large_output_enabled": False,
    "auto_stop_large_output_percent": 90.0,
    "remote_transfer_temp_dir": "/work/jobs",
}
_settings_cache: dict | None = None


def _normalized(values: dict | None) -> dict:
    values = values if isinstance(values, dict) else {}
    try:
        hb_threads = max(0, min(256, int(values.get("hb_threads") or 0)))
    except (TypeError, ValueError):
        hb_threads = 0
    try:
        stop_percent = float(values.get("auto_stop_large_output_percent") or 90.0)
    except (TypeError, ValueError):
        stop_percent = 90.0
    return {
        "hb_threads": hb_threads,
        "auto_stop_large_output_enabled": bool(values.get("auto_stop_large_output_enabled", False)),
        "auto_stop_large_output_percent": round(max(1.0, min(500.0, stop_percent)), 1),
        "remote_transfer_temp_dir": str(values.get("remote_transfer_temp_dir") or "/work/jobs").strip()[:500],
    }


def load_settings() -> dict:
    global _settings_cache
    with SETTINGS_LOCK:
        if _settings_cache is not None:
            return dict(_settings_cache)
        loaded = {}
        for path in (SETTINGS_FILE, SETTINGS_FILE + ".bak"):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    candidate = json.load(handle)
                if isinstance(candidate, dict):
                    loaded = candidate
                    break
            except FileNotFoundError:
                continue
            except Exception as exc:
                print(f"[WARN] Failed to load worker settings: {exc}", flush=True)
        _settings_cache = _normalized({**DEFAULT_SETTINGS, **loaded})
        return dict(_settings_cache)


def save_settings(new_values: dict) -> dict:
    global _settings_cache
    with SETTINGS_LOCK:
        merged = {**load_settings(), **(new_values if isinstance(new_values, dict) else {})}
        _settings_cache = _normalized(merged)
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = f"{SETTINGS_FILE}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_settings_cache, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, SETTINGS_FILE)
        try:
            shutil.copy2(SETTINGS_FILE, SETTINGS_FILE + ".bak")
        except OSError:
            pass
        return dict(_settings_cache)
