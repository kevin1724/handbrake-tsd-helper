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
import threading
import time
from typing import Any

from .config import DATA_DIR


EVENTS_FILE = os.path.join(DATA_DIR.rstrip("/"), "events.json")

# Keep enough history for troubleshooting without letting repeated scan details
# turn a tiny activity feed into a multi-megabyte hot-path file.
MAX_EVENTS = 500
MAX_EVENT_BYTES = 8192
EVENTS_LOCK = threading.RLock()
_events_cache: list[dict] | None = None
_events_signature: tuple[int, int] | None = None


def _ensure_list(obj: Any) -> list:
    return obj if isinstance(obj, list) else []


def _file_signature() -> tuple[int, int] | None:
    try:
        stat = os.stat(EVENTS_FILE)
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return None


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if depth >= 3:
        if isinstance(value, list):
            return {"count": len(value), "truncated": True}
        if isinstance(value, dict):
            return {"keys": list(value)[:12], "truncated": True}
        return str(value)[:500]
    if isinstance(value, list):
        return [_compact_value(row, depth=depth + 1) for row in value[:12]]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _compact_value(row, depth=depth + 1)
            for key, row in list(value.items())[:24]
        }
    return str(value)[:500]


def _compact_event(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    event = {
        "ts": float(raw.get("ts") or 0),
        "level": str(raw.get("level") or "info")[:20],
        "type": str(raw.get("type") or "event")[:100],
        "message": str(raw.get("message") or "")[:1000],
    }
    for key in ("job_id", "src"):
        if raw.get(key):
            event[key] = str(raw.get(key))[:1000]
    for key, value in raw.items():
        if key not in event:
            event[str(key)[:80]] = _compact_value(value)

    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_EVENT_BYTES:
        event = {key: event[key] for key in ("ts", "level", "type", "message", "job_id", "src") if key in event}
        event["details_truncated"] = True
    return event


def _write_events_unlocked(events: list[dict]) -> None:
    global _events_cache, _events_signature
    os.makedirs(DATA_DIR, exist_ok=True)
    temp_path = f"{EVENTS_FILE}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(events, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, EVENTS_FILE)
        _events_cache = events
        _events_signature = _file_signature()
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass


def _load_events_unlocked() -> list[dict]:
    global _events_cache, _events_signature
    signature = _file_signature()
    if _events_cache is not None and signature == _events_signature:
        return _events_cache

    try:
        with open(EVENTS_FILE, "r", encoding="utf-8") as handle:
            raw_events = _ensure_list(json.load(handle))
    except FileNotFoundError:
        raw_events = []
    except Exception as exc:
        print(f"[WARN] Failed to load events.json: {exc}", flush=True)
        raw_events = []

    raw_events.sort(key=lambda event: float(event.get("ts") or 0) if isinstance(event, dict) else 0, reverse=True)
    retained = raw_events[:MAX_EVENTS]
    events = [_compact_event(event) for event in retained]
    needs_compaction = len(raw_events) != len(events) or any(
        event != raw for event, raw in zip(events, retained)
    )
    _events_cache = events
    _events_signature = signature
    if needs_compaction:
        _write_events_unlocked(events)
    return events


def load_events(limit: int = 200) -> list[dict]:
    """Return newest-first events (up to limit)."""
    with EVENTS_LOCK:
        return [event.copy() for event in _load_events_unlocked()[: max(0, int(limit or 0))]]


def load_event_summaries(limit: int = 20) -> list[dict]:
    """Return only fields rendered by compact web and mobile dashboards."""
    keys = ("ts", "level", "type", "message", "job_id", "src")
    return [
        {key: event.get(key) for key in keys if key in event}
        for event in load_events(limit=limit)
    ]


def clear_events() -> None:
    """Delete all events."""
    global _events_cache, _events_signature
    try:
        with EVENTS_LOCK:
            _write_events_unlocked([])
    except Exception as exc:
        _events_cache = []
        _events_signature = None
        print(f"[WARN] Failed to clear events.json: {exc}", flush=True)


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

    ev = _compact_event(ev)
    try:
        with EVENTS_LOCK:
            events = _load_events_unlocked().copy()
            events.insert(0, ev)
            _write_events_unlocked(events[:MAX_EVENTS])
    except Exception as exc:
        print(f"[WARN] Failed to write events.json: {exc}", flush=True)

    return ev
