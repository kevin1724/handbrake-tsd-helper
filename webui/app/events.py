"""Event logging for HandBrake TSD Helper.

This adds a Lidarr-style "Events" feed.

We keep it intentionally simple:
- append events to a JSON list on disk
- keep newest-first
- cap the total count to avoid unbounded growth

An event is a dict like:
  {
    "ts": 1700000000.123,   # unix epoch seconds
    "level": "info"|"warn"|"error",
    "type": "job_queued"|"job_started"|...,
    "message": "human readable",
    "job_id": "..." (optional),
    "src": "/path" (optional)
  }
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .config import DATA_DIR


EVENTS_FILE = os.path.join(DATA_DIR.rstrip("/"), "events.json")

# keep the most recent N events
MAX_EVENTS = 2000


def _ensure_list(obj: Any) -> list:
    return obj if isinstance(obj, list) else []


def load_events(limit: int = 200) -> list[dict]:
    """Return newest-first events (up to limit)."""
    try:
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = []
    except Exception as e:
        print(f"[WARN] Failed to load events.json: {e}", flush=True)
        data = []

    events = _ensure_list(data)
    # newest-first on disk already, but enforce just in case
    events.sort(key=lambda ev: float(ev.get("ts") or 0), reverse=True)
    return events[: max(0, int(limit or 0))]


def clear_events() -> None:
    """Delete all events."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    except Exception as e:
        print(f"[WARN] Failed to clear events.json: {e}", flush=True)


def log_event(
    ev_type: str,
    message: str,
    *,
    level: str = "info",
    job_id: str | None = None,
    src: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Append a new event to disk and return the event dict."""
    ev: dict[str, Any] = {
        "ts": time.time(),
        "level": (level or "info").strip().lower(),
        "type": (ev_type or "event").strip(),
        "message": (message or "").strip(),
    }
    if job_id:
        ev["job_id"] = str(job_id)
    if src:
        ev["src"] = str(src)
    if isinstance(extra, dict) and extra:
        # shallow merge, but avoid clobbering core keys
        for k, v in extra.items():
            if k not in ev:
                ev[k] = v

    try:
        os.makedirs(DATA_DIR, exist_ok=True)

        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except FileNotFoundError:
            existing = []
        except Exception:
            existing = []

        events = _ensure_list(existing)
        # newest-first
        events.insert(0, ev)
        if len(events) > MAX_EVENTS:
            events = events[:MAX_EVENTS]

        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2)

    except Exception as e:
        print(f"[WARN] Failed to write events.json: {e}", flush=True)

    return ev
