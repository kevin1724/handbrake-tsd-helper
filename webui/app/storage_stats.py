"""Storage savings tracking.

Tracks per-encode storage savings and keeps a longer history so you can see
how much space you've recovered over time.

We write a single JSON file: data/storage_stats.json

Schema (loose):
{
  "encodes": [
     {
       "ts": 1700000000.123,
       "job_id": "...",
       "src": "/path/to/source.mkv",
       "out": "/path/to/output-TSD.mkv",
       "preset": "1080"|"4k"|"auto",
       "src_bytes": 123,
       "out_bytes": 456,
       "saved_bytes": 789
     }, ...
  ],
  "totals": {"count": 0, "saved_bytes": 0}
}
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .config import DATA_DIR


STATS_FILE = os.path.join(DATA_DIR.rstrip("/"), "storage_stats.json")
MAX_ROWS = 5000


def _ensure_dict(obj: Any) -> dict:
    return obj if isinstance(obj, dict) else {}


def _ensure_list(obj: Any) -> list:
    return obj if isinstance(obj, list) else []


def _load() -> dict:
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except Exception as e:
        print(f"[WARN] Failed to load storage_stats.json: {e}", flush=True)
        data = {}

    data = _ensure_dict(data)
    data.setdefault("encodes", [])
    data.setdefault("totals", {"count": 0, "saved_bytes": 0})
    data["encodes"] = _ensure_list(data.get("encodes"))
    data["totals"] = _ensure_dict(data.get("totals"))
    data["totals"].setdefault("count", 0)
    data["totals"].setdefault("saved_bytes", 0)
    return data


def _save(data: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save storage_stats.json: {e}", flush=True)


def record_encode(
    *,
    job_id: str,
    src: str,
    out: str,
    preset: str,
    src_bytes: int,
    out_bytes: int,
) -> dict:
    """Record a successful encode's storage savings."""
    try:
        src_bytes_i = int(src_bytes)
    except Exception:
        src_bytes_i = 0
    try:
        out_bytes_i = int(out_bytes)
    except Exception:
        out_bytes_i = 0

    saved = max(0, src_bytes_i - out_bytes_i)

    row = {
        "ts": time.time(),
        "job_id": str(job_id),
        "src": str(src),
        "out": str(out),
        "preset": str(preset),
        "src_bytes": src_bytes_i,
        "out_bytes": out_bytes_i,
        "saved_bytes": saved,
    }

    data = _load()
    encodes = _ensure_list(data.get("encodes"))
    encodes.insert(0, row)  # newest-first
    if len(encodes) > MAX_ROWS:
        encodes = encodes[:MAX_ROWS]
    data["encodes"] = encodes

    totals = _ensure_dict(data.get("totals"))
    totals["count"] = int(totals.get("count") or 0) + 1
    totals["saved_bytes"] = int(totals.get("saved_bytes") or 0) + saved
    data["totals"] = totals

    _save(data)
    return row


def get_summary() -> dict:
    data = _load()
    totals = _ensure_dict(data.get("totals"))
    saved_bytes = int(totals.get("saved_bytes") or 0)
    count = int(totals.get("count") or 0)
    return {
        "count": count,
        "saved_bytes": saved_bytes,
        "saved_gb": round(saved_bytes / (1024**3), 3) if saved_bytes else 0.0,
    }


def list_encodes(limit: int = 200) -> list[dict]:
    data = _load()
    rows = _ensure_list(data.get("encodes"))
    rows.sort(key=lambda r: float(r.get("ts") or 0), reverse=True)
    return rows[: max(0, int(limit or 0))]


def clear_stats() -> None:
    _save({"encodes": [], "totals": {"count": 0, "saved_bytes": 0}})
