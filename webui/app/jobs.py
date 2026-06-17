"""
Job management & dispatcher logic for HandBrake TSD Helper.

This module is responsible for:
- Keeping track of all jobs (in-memory + persisted to disk)
- Running jobs one-at-a-time in a background dispatcher thread
- Parsing HandBrake progress output to update job progress
- Parsing ETA from HandBrake output to estimate remaining time
- Canceling jobs, removing from queue, clearing finished jobs
- Pause / resume queue state

It does NOT know about Flask or HTTP. The web layer should call into
these functions to:
    - create jobs
    - list jobs
    - cancel/remove jobs
    - query status
    - pause/resume queue
"""

import os
import re
import json
import uuid
import signal
import time
import threading
import subprocess
import http.client
import shutil
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import (
    DATA_DIR,
    LOG_DIR,
    JOBS_FILE,
    VIDEO_EXTS,
    ALLOWED_PREFIXES,
)
from .presets import resolve_preset_file_and_name
from .settings import load_settings  # pull in global settings (hb_threads, etc.)
from .events import log_event
from .storage_stats import get_summary as get_storage_summary, record_encode

# -------------------------------------------------------------------
# Global in-memory job state
# -------------------------------------------------------------------
# jobs: main dictionary with all job metadata
#   key: job_id (str UUID)
#   value: {
#       "status": "queued" | "running" | "done" | "error" | "canceled",
#       "src": "/path/to/video.mkv",
#       "preset": "1080" | "4k",
#       "log": "last few KB of HandBrake output",
#       "returncode": int | None,
#       "pid": int | None,
#       "progress": float (0.0 - 100.0),
#       "eta_seconds": float | None   # NEW: remaining time in seconds (if known)
#   }
#
# job_queue: list of job_ids representing run order for "queued" jobs
# queue_paused: if True, dispatcher will NOT start new jobs
# dispatcher_started: ensures we only start one dispatcher thread
# -------------------------------------------------------------------

jobs: dict[str, dict] = {}
job_queue: list[str] = []
queue_paused: bool = False
dispatcher_started: bool = False
dashboard_totals: dict[str, float | int] = {}
TRANSFER_WORK_DIR = os.path.join(DATA_DIR, "node_transfer_work")
PRESET_WORK_DIR = os.path.join(DATA_DIR, "node_job_presets")
OUTPUT_ESTIMATE_CHECKPOINTS = (2, 10, 25, 60, 90)


def _now_ts() -> float:
    return float(time.time())


def _remote_transfer_temp_root(transfer: dict | None = None) -> str:
    transfer = transfer if isinstance(transfer, dict) else {}
    value = str(transfer.get("remote_temp_dir") or "").strip()
    if not value:
        try:
            value = str(load_settings().get("remote_transfer_temp_dir") or "").strip()
        except Exception:
            value = ""
    if not value:
        value = TRANSFER_WORK_DIR
    return os.path.abspath(os.path.expanduser(value))


def _empty_dashboard_totals() -> dict[str, float | int]:
    return {
        "done": 0,
        "error": 0,
        "canceled": 0,
        "saved_bytes": 0,
        "runtime_seconds": 0.0,
        "done_runtime_seconds": 0.0,
        "error_runtime_seconds": 0.0,
        "canceled_runtime_seconds": 0.0,
    }


def _normalize_dashboard_totals(value) -> dict[str, float | int]:
    raw = value if isinstance(value, dict) else {}
    totals = _empty_dashboard_totals()
    for key in ("done", "error", "canceled", "saved_bytes"):
        try:
            totals[key] = max(0, int(raw.get(key) or 0))
        except Exception:
            totals[key] = 0
    try:
        totals["runtime_seconds"] = max(0.0, float(raw.get("runtime_seconds") or 0.0))
    except Exception:
        totals["runtime_seconds"] = 0.0
    for key in ("done_runtime_seconds", "error_runtime_seconds", "canceled_runtime_seconds"):
        try:
            totals[key] = max(0.0, float(raw.get(key) or 0.0))
        except Exception:
            totals[key] = 0.0
    return totals

# Regex to parse HandBrakeCLI progress lines:
# e.g. "Encoding: task 1 of 1, 42.34 % (118.19 fps, avg 118.40 fps, ETA 00h02m34s)"
PROGRESS_RE = re.compile(
    r"Encoding:\s+task\s+\d+\s+of\s+\d+,\s*([\d\.]+)\s*%"
)

# Regex to extract the ETA substring from a line.
# It is intentionally loose: it just grabs the token after "ETA",
# e.g. "00h02m34s", "03m21s", "00:03:21"
ETA_RE = re.compile(r"ETA\s+([0-9hms:]+)")
HDR_PATH_RE = re.compile(
    r"(?:^|[ ._\-\[\(])(?:"
    r"hdr(?:10(?:[ ._\-]*(?:plus|\+))?)?|hdr10plus|hdr10\+|hlg|"
    r"dolby[ ._\-]*vision|dovi|dvhe|dvh1|dv|"
    r"bt[ ._\-]?2020|rec[ ._\-]?2020"
    r")(?=$|[ ._\-\]\)\+])",
    re.IGNORECASE,
)
HDR_SIZE_HINT_RE = re.compile(r"(?:^|[ ._\-\[\(])(?:2160p|4320p|4k|8k|uhd)(?=$|[ ._\-\]\)])", re.IGNORECASE)
HDR_REMUX_HINT_RE = re.compile(r"(?:^|[ ._\-\[\(])(?:remux|uhd[ ._\-]*blu[ ._\-]*ray|uhd[ ._\-]*bd)(?=$|[ ._\-\]\)])", re.IGNORECASE)
HDR_VIDEO_HINT_RE = re.compile(
    r"(?:^|[ ._\-\[\(])(?:hevc|x265|h[ ._\-]*265|main[ ._\-]*10|10[ ._\-]*bit)(?=$|[ ._\-\]\)])",
    re.IGNORECASE,
)
HDR_TENBIT_HINT_RE = re.compile(
    r"(?:^|[ ._\-\[\(])(?:main[ ._\-]*10|10[ ._\-]*bit)(?=$|[ ._\-\]\)])",
    re.IGNORECASE,
)
HDR_AUDIO_HINT_RE = re.compile(
    r"(?:^|[ ._\-\[\(])(?:ddp(?:[ ._\-]*[257]\.?1)?|dd\+|e[ ._\-]*ac3|eac3|atmos|truehd)(?=$|[ ._\-\]\)])",
    re.IGNORECASE,
)


# -------------------------------------------------------------------
# Path helper
# -------------------------------------------------------------------

def is_allowed_path(path: str) -> bool:
    """
    Make sure a given path is under one of the allowed root directories.

    This is a safety check to prevent the UI from browsing / encoding
    files outside of the configured media roots.

    Args:
        path (str): Absolute path to check.

    Returns:
        bool: True if the real path starts with any ALLOWED_PREFIXES.
    """
    real = os.path.realpath(path)
    for prefix in ALLOWED_PREFIXES:
        if real.startswith(os.path.realpath(prefix)):
            return True
    return False


# -------------------------------------------------------------------
# ETA parsing helper
# -------------------------------------------------------------------

def _parse_eta_to_seconds(eta_str: str) -> float | None:
    """
    Convert an ETA string from HandBrake into seconds.

    Supports formats like:
      - "00h02m34s"
      - "03m21s"
      - "00:03:21"
      - "03:21"

    Returns:
        float | None: total seconds, or None if we can't parse.
    """
    if not eta_str:
        return None

    s = eta_str.strip()

    # Case 1: colon-separated formats "HH:MM:SS" or "MM:SS"
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 3:
                h, m, sec = [int(p) for p in parts]
            elif len(parts) == 2:
                h = 0
                m, sec = [int(p) for p in parts]
            else:
                return None
        except ValueError:
            return None
        return float(h * 3600 + m * 60 + sec)

    # Case 2: letter-based formats like "01h23m45s" or "03m21s"
    # Grab all "<number><unit>" pairs.
    matches = re.findall(r"(\d+)([hms])", s)
    if not matches:
        return None

    total = 0
    for value, unit in matches:
        try:
            v = int(value)
        except ValueError:
            continue
        if unit == "h":
            total += v * 3600
        elif unit == "m":
            total += v * 60
        elif unit == "s":
            total += v

    return float(total) if total > 0 else None


def _looks_like_hdr_path(path: str) -> bool:
    """Fast metadata hint used for job history and predictions."""
    text = f"{os.path.basename(path or '')} {path or ''}"
    if HDR_PATH_RE.search(text):
        return True

    has_size = bool(HDR_SIZE_HINT_RE.search(text))
    has_remux = bool(HDR_REMUX_HINT_RE.search(text))
    has_video = bool(HDR_VIDEO_HINT_RE.search(text))
    has_tenbit = bool(HDR_TENBIT_HINT_RE.search(text))
    has_audio = bool(HDR_AUDIO_HINT_RE.search(text))

    if has_size and (has_remux or has_video or has_audio):
        return True
    return bool(has_remux and has_tenbit)


def _encoded_output_is_valid(path: str) -> tuple[bool, str]:
    """Return True only when the output exists, has bytes, and ffprobe can read it."""
    if not path or not os.path.isfile(path):
        return False, "output file missing"

    try:
        if int(os.path.getsize(path)) <= 0:
            return False, "output file is empty"
    except Exception as e:
        return False, f"could not read output size: {e}"

    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        return True, "ffprobe unavailable; size check passed"
    except subprocess.TimeoutExpired:
        return False, "ffprobe timed out"
    except Exception as e:
        return False, f"ffprobe failed: {e}"

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip()
        return False, detail[:240] or "ffprobe could not read output"

    try:
        duration = float((probe.stdout or "").strip() or 0.0)
    except Exception:
        duration = 0.0
    if duration <= 0:
        return False, "output duration is missing"
    return True, "ok"


def _safe_transfer_filename(name: str, fallback: str = "source.mkv") -> str:
    value = os.path.basename(str(name or "").replace("\\", "/")).strip()
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
    value = value.strip(" .")
    return value or fallback


def _human_rate(bytes_per_second: float) -> str:
    try:
        value = float(bytes_per_second or 0.0)
    except Exception:
        value = 0.0
    if value <= 0:
        return ""
    mb = value / (1024 ** 2)
    if mb >= 1:
        return f"{mb:.2f} MB/s"
    return f"{max(1, round(value / 1024))} KB/s"


def _transfer_progress_payload(phase: str, transferred: int, total: int, started_at: float) -> dict:
    now = _now_ts()
    elapsed = max(0.001, now - float(started_at or now))
    transferred_i = max(0, int(transferred or 0))
    total_i = max(0, int(total or 0))
    speed = transferred_i / elapsed if transferred_i > 0 else 0.0
    remaining = max(0, total_i - transferred_i) if total_i else 0
    percent = (transferred_i / total_i * 100.0) if total_i else 0.0
    eta = int(round(remaining / speed)) if speed > 0 and remaining > 0 else None
    return {
        "phase": phase,
        "bytes": transferred_i,
        "total_bytes": total_i,
        "remaining_bytes": remaining,
        "percent": round(max(0.0, min(100.0, percent)), 2),
        "speed_bps": round(speed, 2),
        "speed_label": _human_rate(speed),
        "eta_seconds": eta,
        "updated_at": now,
    }


def _normalize_preset_bundle(bundle) -> dict | None:
    if not isinstance(bundle, dict):
        return None
    contents = bundle.get("contents")
    if isinstance(contents, dict):
        contents = json.dumps(contents, indent=2)
    contents = str(contents or "")
    if not contents.strip():
        return None
    try:
        json.loads(contents)
    except Exception:
        return None
    file_name = _safe_transfer_filename(bundle.get("file_name") or bundle.get("filename") or "controller-preset.json", "controller-preset.json")
    if not file_name.lower().endswith(".json"):
        file_name += ".json"
    return {
        "key": str(bundle.get("key") or "").strip()[:32],
        "file_name": file_name,
        "name": str(bundle.get("name") or "").strip()[:160],
        "contents": contents,
        "source": "controller",
    }


def _materialize_job_preset(job_id: str, bundle) -> tuple[str, str, str] | None:
    clean = _normalize_preset_bundle(bundle)
    if not clean:
        return None
    work_dir = os.path.join(PRESET_WORK_DIR, str(job_id))
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, clean["file_name"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(clean["contents"])
    return path, clean.get("name") or "", work_dir


def _cleanup_job_preset_dir(path: str) -> None:
    if not path:
        return
    try:
        real = os.path.realpath(path)
        root = os.path.realpath(PRESET_WORK_DIR)
        if os.path.commonpath([real, root]) == root and os.path.isdir(real):
            shutil.rmtree(real, ignore_errors=True)
    except Exception:
        pass


def _maybe_update_output_estimate(job: dict, out_path: str, progress: float) -> bool:
    try:
        pct = float(progress or 0.0)
    except Exception:
        return False
    if pct <= 0 or pct >= 100 or not out_path:
        return False

    seen = job.get("estimate_checkpoints_seen")
    if not isinstance(seen, list):
        seen = []
    next_checkpoint = next((point for point in OUTPUT_ESTIMATE_CHECKPOINTS if pct >= point and point not in seen), None)
    if next_checkpoint is None:
        return False

    seen.append(next_checkpoint)
    job["estimate_checkpoints_seen"] = seen
    try:
        current_bytes = int(os.path.getsize(out_path))
    except Exception:
        return True
    if current_bytes <= 0:
        return True

    estimated = int(round(current_bytes / max(0.01, pct / 100.0)))
    job["estimated_out_bytes"] = estimated
    job["estimated_out_current_bytes"] = current_bytes
    job["estimated_out_checked_progress"] = round(pct, 2)
    job["estimated_out_updated_at"] = _now_ts()
    return True


def _download_transfer_source(url: str, token: str, worker_node_id: str, destination: str, expected_size: int = 0, progress_callback=None) -> int:
    if not url or not token:
        raise RuntimeError("transfer download is missing URL or token")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    part_path = destination + ".part"
    req = Request(
        url,
        method="GET",
        headers={
            "X-Transfer-Token": token,
            "X-Worker-Node-Id": str(worker_node_id or ""),
        },
    )
    try:
        with urlopen(req, timeout=60) as res, open(part_path, "wb") as f:
            transferred = 0
            header_size = 0
            try:
                header_size = int(res.headers.get("Content-Length") or 0)
            except Exception:
                header_size = 0
            total = int(expected_size or header_size or 0)
            if progress_callback:
                progress_callback("downloading", 0, total, force=True)
            while True:
                chunk = res.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                transferred += len(chunk)
                if progress_callback:
                    progress_callback("downloading", transferred, total)
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        raise RuntimeError(detail[:240] or str(e))
    except (URLError, TimeoutError, OSError) as e:
        raise RuntimeError(str(e))

    size = int(os.path.getsize(part_path))
    if expected_size and size != int(expected_size):
        try:
            os.remove(part_path)
        except FileNotFoundError:
            pass
        raise RuntimeError(f"downloaded source size mismatch ({size} != {expected_size})")
    if progress_callback:
        progress_callback("downloaded", size, int(expected_size or size), force=True)
    os.replace(part_path, destination)
    return size


def _upload_transfer_output(url: str, token: str, worker_node_id: str, out_path: str, *, job_id: str, duration_seconds: float | None, progress_callback=None) -> dict:
    if not url or not token:
        raise RuntimeError("transfer upload is missing URL or token")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("invalid transfer upload URL")
    size = int(os.path.getsize(out_path))
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    conn = conn_cls(parsed.netloc, timeout=60)
    try:
        conn.putrequest("POST", target)
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        conn.putheader("X-Transfer-Token", token)
        conn.putheader("X-Worker-Node-Id", str(worker_node_id or ""))
        conn.putheader("X-Worker-Job-Id", str(job_id or ""))
        conn.putheader("X-Output-Filename", os.path.basename(out_path))
        if duration_seconds is not None:
            conn.putheader("X-Encode-Duration-Seconds", str(round(float(duration_seconds), 3)))
        conn.endheaders()
        with open(out_path, "rb") as f:
            sent = 0
            if progress_callback:
                progress_callback("uploading", 0, size, force=True)
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)
                sent += len(chunk)
                if progress_callback:
                    progress_callback("uploading", sent, size)
        if progress_callback:
            progress_callback("uploaded", size, size, force=True)
        res = conn.getresponse()
        body = res.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body or "{}")
        except Exception:
            payload = {"error": body[:240]}
        if res.status >= 400 or not payload.get("ok"):
            raise RuntimeError(payload.get("error") or f"transfer upload failed ({res.status})")
        return payload if isinstance(payload, dict) else {}
    finally:
        conn.close()


def _cleanup_transfer_work_dir(path: str, transfer: dict | None = None) -> None:
    if not path:
        return
    try:
        real = os.path.realpath(path)
        root = os.path.realpath(_remote_transfer_temp_root(transfer))
        if os.path.commonpath([real, root]) == root and os.path.isdir(real):
            shutil.rmtree(real, ignore_errors=True)
    except Exception:
        pass


def _remote_transfer_public(transfer: dict | None) -> dict:
    transfer = transfer if isinstance(transfer, dict) else {}
    return {
        "id": transfer.get("id") or transfer.get("transfer_id") or "",
        "controller_url": transfer.get("controller_url") or "",
        "original_path": transfer.get("original_path") or "",
        "source_basename": transfer.get("source_basename") or "",
        "source_size": transfer.get("source_size") or 0,
        "status": transfer.get("status") or "",
        "remote_temp_dir": transfer.get("remote_temp_dir") or "",
        "progress": transfer.get("progress") if isinstance(transfer.get("progress"), dict) else {},
    }


# -------------------------------------------------------------------
# Persistence: saving / loading jobs.json
# -------------------------------------------------------------------

def save_jobs():
    """
    Persist current job metadata + queue + queue_paused flag to disk.

    Writes a JSON file to JOBS_FILE. We intentionally do NOT persist pids,
    because the OS process won't survive container restarts anyway.
    """
    global queue_paused, dashboard_totals

    try:
        serializable = {}
        for jid, j in jobs.items():
            serializable[jid] = {
                "status": j.get("status"),
                "src": j.get("src"),
                "preset": j.get("preset"),
                "extra_args": j.get("extra_args", ""),
                "mode": j.get("mode", "local"),
                "transfer": j.get("transfer") if isinstance(j.get("transfer"), dict) else None,
                "preset_bundle": _normalize_preset_bundle(j.get("preset_bundle")),
                "log": j.get("log", ""),
                "returncode": j.get("returncode"),
                "pid": None,  # never persist the actual pid
                "progress": float(j.get("progress") or 0.0),
                # NEW: persist ETA if present
                "eta_seconds": j.get("eta_seconds"),
                "estimated_out_bytes": j.get("estimated_out_bytes"),
                "estimated_out_current_bytes": j.get("estimated_out_current_bytes"),
                "estimated_out_checked_progress": j.get("estimated_out_checked_progress"),
                "estimated_out_updated_at": j.get("estimated_out_updated_at"),
                "estimate_checkpoints_seen": j.get("estimate_checkpoints_seen") if isinstance(j.get("estimate_checkpoints_seen"), list) else [],
                # Storage tracking
                "src_bytes": j.get("src_bytes"),
                "out_bytes": j.get("out_bytes"),
                "saved_bytes": j.get("saved_bytes"),
                "out_path": j.get("out_path"),
                "is_hdr": bool(j.get("is_hdr", False) or _looks_like_hdr_path(j.get("src", ""))),
                "created_at": j.get("created_at"),
                "started_at": j.get("started_at"),
                "finished_at": j.get("finished_at"),
                "duration_seconds": j.get("duration_seconds"),
            }

        state = {
            "jobs": serializable,
            "queue": list(job_queue),
            "queue_paused": queue_paused,
            "dashboard_totals": _normalize_dashboard_totals(dashboard_totals),
        }

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(JOBS_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[WARN] Failed to save jobs.json: {e}", flush=True)


def load_jobs():
    """
    Load previous jobs + queue state from JOBS_FILE.

    - Any job that was "running" when we last saved is treated as "queued"
      again (since the process is gone after restart).
    - We also restore the queue order and queue_paused flag.
    """
    global jobs, job_queue, queue_paused, dashboard_totals

    if not os.path.isfile(JOBS_FILE):
        jobs = {}
        job_queue = []
        queue_paused = False
        dashboard_totals = _empty_dashboard_totals()
        return

    try:
        with open(JOBS_FILE, "r") as f:
            state = json.load(f)

        data = state.get("jobs") or {}
        q = state.get("queue") or []
        queue_paused = bool(state.get("queue_paused", False))
        dashboard_totals = _normalize_dashboard_totals(state.get("dashboard_totals"))

        jobs = {}
        for jid, j in data.items():
            if not isinstance(j, dict):
                continue

            status = j.get("status", "unknown")
            # If the container died while it was running, treat it as queued again.
            if status == "running":
                status = "queued"

            jobs[jid] = {
                "status": status,
                "src": j.get("src"),
                "preset": j.get("preset"),
                "extra_args": j.get("extra_args", ""),
                "mode": j.get("mode", "local"),
                "transfer": j.get("transfer") if isinstance(j.get("transfer"), dict) else None,
                "preset_bundle": _normalize_preset_bundle(j.get("preset_bundle")),
                "log": j.get("log", ""),
                "returncode": j.get("returncode"),
                "pid": None,
                "progress": float(j.get("progress") or 0.0),
                # NEW: restore ETA if it was saved
                "eta_seconds": j.get("eta_seconds"),
                "estimated_out_bytes": j.get("estimated_out_bytes"),
                "estimated_out_current_bytes": j.get("estimated_out_current_bytes"),
                "estimated_out_checked_progress": j.get("estimated_out_checked_progress"),
                "estimated_out_updated_at": j.get("estimated_out_updated_at"),
                "estimate_checkpoints_seen": j.get("estimate_checkpoints_seen") if isinstance(j.get("estimate_checkpoints_seen"), list) else [],
                # Storage tracking
                "src_bytes": j.get("src_bytes"),
                "out_bytes": j.get("out_bytes"),
                "saved_bytes": j.get("saved_bytes"),
                "out_path": j.get("out_path"),
                "is_hdr": bool(j.get("is_hdr", False) or _looks_like_hdr_path(j.get("src", ""))),
                "created_at": j.get("created_at"),
                "started_at": j.get("started_at"),
                "finished_at": j.get("finished_at"),
                "duration_seconds": j.get("duration_seconds"),
            }

        # rebuild queue, keeping only jobs that still exist and are queued
        job_queue = [
            jid
            for jid in q
            if jid in jobs and jobs[jid].get("status") == "queued"
        ]

    except Exception as e:
        print(f"[WARN] Failed to load jobs.json: {e}", flush=True)
        jobs = {}
        job_queue = []
        queue_paused = False
        dashboard_totals = _empty_dashboard_totals()


def initialize_jobs_system():
    """
    Call this once at app startup.

    - Loads existing jobs from disk
    - Starts dispatcher thread (which just idles if there is nothing queued)
    """
    load_jobs()
    ensure_dispatcher()

def _find_existing_active_job_for_src(src: str) -> str | None:
    """
    Check if there is already a job for this src that is either queued
    or currently running.

    We treat those as "active", so the same file should not be added
    to the queue a second time while one of these is in-flight.

    Returns:
        job_id (str) if found, otherwise None.
    """
    for jid, j in jobs.items():
        if j.get("src") == src and j.get("status") in ("queued", "running"):
            return jid
    return None


# -------------------------------------------------------------------
# Core job creation / lookup helpers (used by routes)
# -------------------------------------------------------------------

def create_job(src: str, preset: str, extra_args: str = "", preset_bundle: dict | None = None) -> str:
    """
    Create a single job and append it to the queue.

    This does NOT validate src path or preset value — the web layer
    should do that before calling this function.

    IMPORTANT:
      - If there is already a job for this src with status "queued"
        or "running", we do NOT create a duplicate. Instead, we just
        return the existing job_id.

    Args:
        src (str): Absolute path to source video file.
        preset (str): "1080" or "4k"

    Returns:
        str: job_id (UUID string, or existing one if already active)
    """
    # Check for an already-active job for this src
    existing_id = _find_existing_active_job_for_src(src)
    if existing_id is not None:
        # Do not enqueue a second job for the same src
        return existing_id

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "src": src,
        "preset": preset,
        "extra_args": extra_args or "",
        "mode": "local",
        "transfer": None,
        "preset_bundle": _normalize_preset_bundle(preset_bundle),
        "log": "",
        "returncode": None,
        "pid": None,
        "progress": 0.0,
        "eta_seconds": None,  # if you already added ETA support
        "estimated_out_bytes": None,
        "estimated_out_current_bytes": None,
        "estimated_out_checked_progress": None,
        "estimated_out_updated_at": None,
        "estimate_checkpoints_seen": [],
        # Storage tracking (filled on completion)
        "src_bytes": None,
        "out_bytes": None,
        "saved_bytes": None,
        "out_path": None,
        "is_hdr": _looks_like_hdr_path(src),
        "created_at": _now_ts(),
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
    }
    job_queue.append(job_id)
    save_jobs()
    log_event(
        "job_queued",
        f"Queued: {os.path.basename(src)} ({preset})",
        job_id=job_id,
        src=src,
    )
    ensure_dispatcher()
    return job_id



def create_jobs_batch(files_and_presets: list[tuple[str, str]]) -> int:
    """
    Create a batch of jobs (used for folder / recursive batch encode).

    For each (src, preset):
      - If there is already an "active" job (queued/running) for src,
        we skip creating a duplicate.
      - We also skip duplicates within the same batch call.

    Args:
        files_and_presets (list[(src, preset)]):
            List of tuples, each containing:
                - src: str (absolute path to file)
                - preset: str ("1080" or "4k")

    Returns:
        int: number of NEW jobs created (duplicates skipped)
    """
    count = 0
    seen_in_batch: set[str] = set()

    for src, preset in files_and_presets:
        # Avoid duplicates within the same batch call
        if src in seen_in_batch:
            continue
        seen_in_batch.add(src)

        # Skip if there is already an active job for this src
        if _find_existing_active_job_for_src(src) is not None:
            continue

        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            "status": "queued",
            "src": src,
            "preset": preset,
            "mode": "local",
            "transfer": None,
            "preset_bundle": None,
            "log": "",
            "returncode": None,
            "pid": None,
            "progress": 0.0,
            "eta_seconds": None,  # remove if you don't use ETA
            "estimated_out_bytes": None,
            "estimated_out_current_bytes": None,
            "estimated_out_checked_progress": None,
            "estimated_out_updated_at": None,
            "estimate_checkpoints_seen": [],
            "src_bytes": None,
            "out_bytes": None,
            "saved_bytes": None,
            "out_path": None,
            "is_hdr": _looks_like_hdr_path(src),
            "created_at": _now_ts(),
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
        }
        job_queue.append(job_id)
        count += 1

        log_event(
            "job_queued",
            f"Queued: {os.path.basename(src)} ({preset})",
            job_id=job_id,
            src=src,
        )

    if count > 0:
        save_jobs()
        ensure_dispatcher()

    return count


def create_remote_transfer_job(src: str, preset: str, transfer: dict, extra_args: str = "", preset_bundle: dict | None = None) -> tuple[str, bool]:
    """
    Queue a job whose source is downloaded from a paired controller/storage node.

    The visible src remains the original controller path, but HandBrake runs
    against a temporary local copy created when the job starts.
    """
    display_src = str(src or transfer.get("original_path") or transfer.get("source_basename") or "").strip()
    existing_id = _find_existing_active_job_for_src(display_src)
    if existing_id is not None:
        return existing_id, False

    job_id = str(uuid.uuid4())
    clean_transfer = {
        "id": str(transfer.get("id") or transfer.get("transfer_id") or "").strip(),
        "controller_url": str(transfer.get("controller_url") or "").strip().rstrip("/"),
        "source_url": str(transfer.get("source_url") or "").strip(),
        "upload_url": str(transfer.get("upload_url") or "").strip(),
        "download_token": str(transfer.get("download_token") or "").strip(),
        "upload_token": str(transfer.get("upload_token") or "").strip(),
        "worker_node_id": str(transfer.get("worker_node_id") or "").strip(),
        "original_path": display_src,
        "source_basename": _safe_transfer_filename(transfer.get("source_basename") or os.path.basename(display_src)),
        "source_size": int(transfer.get("source_size") or 0),
        "remote_temp_dir": str(transfer.get("remote_temp_dir") or "").strip()[:500],
        "status": "queued",
    }
    jobs[job_id] = {
        "status": "queued",
        "src": display_src,
        "preset": preset,
        "extra_args": extra_args or "",
        "mode": "remote_transfer",
        "transfer": clean_transfer,
        "preset_bundle": _normalize_preset_bundle(preset_bundle),
        "log": "",
        "returncode": None,
        "pid": None,
        "progress": 0.0,
        "eta_seconds": None,
        "estimated_out_bytes": None,
        "estimated_out_current_bytes": None,
        "estimated_out_checked_progress": None,
        "estimated_out_updated_at": None,
        "estimate_checkpoints_seen": [],
        "src_bytes": clean_transfer["source_size"] or None,
        "out_bytes": None,
        "saved_bytes": None,
        "out_path": None,
        "is_hdr": _looks_like_hdr_path(display_src),
        "created_at": _now_ts(),
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
    }
    job_queue.append(job_id)
    save_jobs()
    log_event(
        "node_transfer_job_queued",
        f"Queued remote-transfer job: {os.path.basename(display_src)} ({preset})",
        job_id=job_id,
        src=display_src,
    )
    ensure_dispatcher()
    return job_id, True



def get_job(job_id: str) -> dict | None:
    """
    Fetch a job by ID.

    Returns:
        dict | None: job dict or None if not found
    """
    return jobs.get(job_id)


def list_jobs_for_api() -> list[dict]:
    """
    Build a list of job dictionaries suitable for JSON responses.

    Each job dict includes:
      - id
      - src
      - preset
      - status
      - returncode
      - progress
      - eta_seconds (float | None)
      - has_log (bool)
    """
    job_items = []
    for jid, j in jobs.items():
        log_path = os.path.join(LOG_DIR, f"{jid}.log")
        has_log = os.path.isfile(log_path)

        eta_val = j.get("eta_seconds")
        if eta_val is not None:
            try:
                eta_val = float(eta_val)
            except (TypeError, ValueError):
                eta_val = None

        job_items.append(
            {
                "id": jid,
                "src": j.get("src"),
                "preset": j.get("preset"),
                "mode": j.get("mode", "local"),
                "transfer": _remote_transfer_public(j.get("transfer")) if j.get("mode") == "remote_transfer" else None,
                "status": j.get("status"),
                "returncode": j.get("returncode"),
                "progress": float(j.get("progress") or 0.0),
                "eta_seconds": eta_val,
                "has_log": has_log,
                "estimated_out_bytes": j.get("estimated_out_bytes"),
                "estimated_out_gb": round((int(j.get("estimated_out_bytes") or 0) / (1024**3)), 3)
                if j.get("estimated_out_bytes") is not None
                else None,
                "estimated_out_current_bytes": j.get("estimated_out_current_bytes"),
                "estimated_out_checked_progress": j.get("estimated_out_checked_progress"),
                "estimated_out_updated_at": j.get("estimated_out_updated_at"),
                # Storage tracking
                "src_bytes": j.get("src_bytes"),
                "out_bytes": j.get("out_bytes"),
                "saved_bytes": j.get("saved_bytes"),
                "saved_gb": round((int(j.get("saved_bytes") or 0) / (1024**3)), 3)
                if j.get("saved_bytes") is not None
                else None,
                "is_hdr": bool(j.get("is_hdr", False) or _looks_like_hdr_path(j.get("src", ""))),
                "created_at": j.get("created_at"),
                "started_at": j.get("started_at"),
                "finished_at": j.get("finished_at"),
                "duration_seconds": j.get("duration_seconds"),
                "queue_position": (job_queue.index(jid) + 1) if jid in job_queue and j.get("status") == "queued" else None,
            }
        )

    def _sort_key(item: dict):
        status = str(item.get("status") or "").lower()
        created = float(item.get("created_at") or 0.0)
        if status == "running":
            return (0, 0, -created, item["id"])
        if status == "queued":
            pos = int(item.get("queue_position") or 999999)
            return (1, pos, -created, item["id"])
        return (2, 0, -created, item["id"])

    # Keep the visible queue aligned with the real queue order.
    job_items.sort(key=_sort_key)
    return job_items


# -------------------------------------------------------------------
# Dispatcher + HandBrake process runner
# -------------------------------------------------------------------

def run_encode(job_id: str, src_path: str, preset_key: str):
    """
    Run a single HandBrake encode (called by dispatcher).

    - Sets job status to "running"
    - Spawns /worker/encode-one.sh with proper env vars
    - Streams output into a log file & memory
    - Parses progress using PROGRESS_RE
    - Parses ETA using ETA_RE
    - Handles cancellation (if job["status"] is set to "canceled")
    - Updates final status to "done" or "error"
    """
    job = jobs[job_id]
    display_src_path = src_path
    encode_src_path = src_path
    transfer = job.get("transfer") if isinstance(job.get("transfer"), dict) else {}
    remote_transfer = job.get("mode") == "remote_transfer" and bool(transfer)
    transfer_work_dir = ""
    preset_work_dir = ""

    job["status"] = "running"
    job["progress"] = 0.0
    job["started_at"] = _now_ts()
    job["finished_at"] = None
    job["duration_seconds"] = None
    job["eta_seconds"] = None  # reset ETA at the start
    # Reset storage tracking fields for this run
    job["src_bytes"] = None
    job["out_bytes"] = None
    job["saved_bytes"] = None
    job["out_path"] = None
    job["is_hdr"] = bool(job.get("is_hdr", False) or _looks_like_hdr_path(display_src_path))
    job["estimated_out_bytes"] = None
    job["estimated_out_current_bytes"] = None
    job["estimated_out_checked_progress"] = None
    job["estimated_out_updated_at"] = None
    job["estimate_checkpoints_seen"] = []

    transfer_progress_state = {"phase": "", "started_at": _now_ts(), "last_save": 0.0}

    def update_transfer_progress(phase: str, transferred: int, total: int, force: bool = False) -> None:
        if not remote_transfer:
            return
        now = _now_ts()
        if phase != transfer_progress_state.get("phase"):
            transfer_progress_state["phase"] = phase
            transfer_progress_state["started_at"] = now
            transfer_progress_state["last_save"] = 0.0
        transfer["status"] = phase
        transfer["progress"] = _transfer_progress_payload(
            phase,
            int(transferred or 0),
            int(total or 0),
            float(transfer_progress_state.get("started_at") or now),
        )
        job["transfer"] = transfer
        if force or now - float(transfer_progress_state.get("last_save") or 0.0) >= 1.0:
            transfer_progress_state["last_save"] = now
            save_jobs()

    if remote_transfer:
        try:
            transfer_work_dir = os.path.join(_remote_transfer_temp_root(transfer), job_id)
            basename = _safe_transfer_filename(transfer.get("source_basename") or os.path.basename(display_src_path))
            encode_src_path = os.path.join(transfer_work_dir, basename)
            job["log"] = "Downloading source from controller...\n"
            transfer["status"] = "downloading"
            transfer["work_dir"] = transfer_work_dir
            transfer["local_src"] = encode_src_path
            job["transfer"] = transfer
            save_jobs()
            downloaded_size = _download_transfer_source(
                transfer.get("source_url") or "",
                transfer.get("download_token") or "",
                transfer.get("worker_node_id") or "",
                encode_src_path,
                int(transfer.get("source_size") or 0),
                progress_callback=update_transfer_progress,
            )
            job["src_bytes"] = downloaded_size
            transfer["status"] = "downloaded"
            update_transfer_progress("downloaded", downloaded_size, int(transfer.get("source_size") or downloaded_size), force=True)
            job["transfer"] = transfer
            save_jobs()
        except Exception as e:
            job["status"] = "error"
            job["returncode"] = None
            job["log"] = (job.get("log") or "") + f"Remote source download failed: {e}\n"
            transfer["status"] = "error"
            transfer["error"] = str(e)[:240]
            job["transfer"] = transfer
            log_event(
                "node_transfer_error",
                f"Remote source download failed: {os.path.basename(display_src_path)} ({e})",
                level="error",
                job_id=job_id,
                src=display_src_path,
            )
            job["eta_seconds"] = None
            job["finished_at"] = _now_ts()
            job["pid"] = None
            transfer.pop("download_token", None)
            transfer.pop("upload_token", None)
            transfer.pop("local_src", None)
            transfer.pop("work_dir", None)
            job["transfer"] = transfer
            _cleanup_transfer_work_dir(transfer_work_dir, transfer)
            save_jobs()
            return

    # Capture source size before the success path deletes the original.
    try:
        if job.get("src_bytes") is None:
            job["src_bytes"] = int(os.path.getsize(encode_src_path))
    except Exception:
        job["src_bytes"] = None

    # Predict output path (must match worker/encode-one.sh)
    try:
        suffix = (os.environ.get("SUFFIX") or "TSD").strip() or "TSD"
    except Exception:
        suffix = "TSD"
    d = os.path.dirname(encode_src_path)
    base = os.path.basename(encode_src_path)
    name, ext = os.path.splitext(base)
    out_path = os.path.join(d, f"{name}-{suffix}{ext}")
    out_path_existed_before = os.path.exists(out_path)
    job["out_path"] = out_path

    log_event(
        "job_started",
        f"Started: {os.path.basename(display_src_path)} ({preset_key})",
        job_id=job_id,
        src=display_src_path,
    )
    save_jobs()

    # ------------------------------------------------------------
    # ENVIRONMENT SETUP FOR WORKER SCRIPT
    # - SRC: path to source video (always required)
    # - HB_PRESET_FILE / HB_PRESET_NAME: resolved from preset key
    # - HB_THREADS: optional override from settings.py (Settings page)
    # ------------------------------------------------------------
    env = os.environ.copy()
    env["SRC"] = encode_src_path  # encode-one.sh uses this
    # keep SUFFIX consistent across the stack
    env["SUFFIX"] = suffix

    # CPU thread setting pulled from global Settings:
    # Settings page stores hb_threads in settings.json.
    # If hb_threads > 0, we pass it down as HB_THREADS so encode-one.sh
    # can include "--encopts threads=<N>" when calling HandBrakeCLI.
    try:
        hb_threads_val = load_settings().get("hb_threads", 0)
        hb_threads = int(hb_threads_val or 0)
    except (TypeError, ValueError):
        hb_threads = 0

    if hb_threads > 0:
        env["HB_THREADS"] = str(hb_threads)
        # Example consumed downstream:
        #   HandBrakeCLI --encopts threads=$HB_THREADS ...
        # If hb_threads == 0 (auto), we simply do not set HB_THREADS.

    # Resolve HB_PRESET_FILE + HB_PRESET_NAME based on preset key ("1080" or "4k")
    preset_override = _materialize_job_preset(job_id, job.get("preset_bundle"))
    if preset_override:
        preset_file, preset_name, preset_work_dir = preset_override
        if not preset_name:
            _default_file, preset_name = resolve_preset_file_and_name(preset_key)
    else:
        preset_file, preset_name = resolve_preset_file_and_name(preset_key)
    env["HB_PRESET_FILE"] = preset_file
    env["HB_PRESET_NAME"] = preset_name

    # Optional extra HandBrakeCLI args (used by Size Wizard, etc.)
    env["HB_EXTRA_ARGS"] = job.get("extra_args", "")

    # Optional: additional HandBrakeCLI args (Size Wizard, etc.)
    env["HB_EXTRA_ARGS"] = job.get("extra_args", "")

    # Log file location for this job
    log_path = os.path.join(LOG_DIR, f"{job_id}.log")

    # Spawn worker shell script
    proc = subprocess.Popen(
        ["/bin/sh", "/worker/encode-one.sh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
    )

    job["pid"] = proc.pid
    save_jobs()

    log_lines: list[str] = []

    # ------------------------------------------------------------
    # STREAM OUTPUT:
    # - Write full log to file
    # - Keep in-memory tail for quick viewing in web UI
    # - Update progress and ETA based on HandBrake output
    # ------------------------------------------------------------
    with open(log_path, "w") as lf:
        for line in proc.stdout:
            lf.write(line)
            lf.flush()

            log_lines.append(line)
            # Keep just the last ~4000 characters as an in-memory tail
            job["log"] = "".join(log_lines)[-4000:]

            # Parse progress from this line, if present
            m = PROGRESS_RE.search(line)
            if m:
                try:
                    job["progress"] = float(m.group(1))
                except ValueError:
                    pass
                else:
                    if _maybe_update_output_estimate(job, out_path, job["progress"]):
                        save_jobs()

            # Parse ETA from this line, if present
            em = ETA_RE.search(line)
            if em:
                eta_str = em.group(1)
                eta_seconds = _parse_eta_to_seconds(eta_str)
                job["eta_seconds"] = eta_seconds

            # If the job was canceled externally, stop reading further
            if job.get("status") == "canceled":
                break

    # Wait for process to exit
    ret = proc.wait()
    job["returncode"] = ret

    # If job was not canceled, finalize with done/error
    if job.get("status") != "canceled":
        job["status"] = "done" if ret == 0 else "error"
        if ret == 0:
            job["progress"] = 100.0

    output_validation_error = ""

    # Storage tracking + history (only when we have a real output file)
    if job.get("status") == "done" and ret == 0:
        try:
            output_ok, output_reason = _encoded_output_is_valid(out_path)
            if output_ok and out_path and os.path.isfile(out_path):
                out_bytes = int(os.path.getsize(out_path))
                job["out_bytes"] = out_bytes
                job["estimated_out_bytes"] = out_bytes

                src_bytes = job.get("src_bytes")
                try:
                    src_bytes_i = int(src_bytes) if src_bytes is not None else 0
                except Exception:
                    src_bytes_i = 0

                saved_bytes = max(0, src_bytes_i - out_bytes)
                job["saved_bytes"] = saved_bytes
                duration_seconds_for_stats = None
                if job.get("started_at") is not None:
                    try:
                        duration_seconds_for_stats = max(0.0, _now_ts() - float(job["started_at"]))
                    except Exception:
                        duration_seconds_for_stats = None

                if remote_transfer:
                    transfer["status"] = "uploading"
                    job["transfer"] = transfer
                    save_jobs()
                    upload_result = _upload_transfer_output(
                        transfer.get("upload_url") or "",
                        transfer.get("upload_token") or "",
                        transfer.get("worker_node_id") or "",
                        out_path,
                        job_id=job_id,
                        duration_seconds=duration_seconds_for_stats,
                        progress_callback=update_transfer_progress,
                    )
                    controller_out = upload_result.get("out_path") or out_path
                    controller_out_bytes = int(upload_result.get("out_bytes") or out_bytes)
                    controller_saved = int(upload_result.get("saved_bytes") or saved_bytes)
                    job["out_path"] = controller_out
                    job["out_bytes"] = controller_out_bytes
                    job["saved_bytes"] = controller_saved
                    job["estimated_out_bytes"] = controller_out_bytes
                    transfer["status"] = "complete"
                    update_transfer_progress("complete", controller_out_bytes, controller_out_bytes, force=True)
                    transfer["controller_out_path"] = controller_out
                    transfer["source_deleted"] = bool(upload_result.get("source_deleted"))
                    job["transfer"] = transfer
                    log_event(
                        "node_transfer_finished",
                        f"Remote transfer finished: {os.path.basename(display_src_path)} - saved {round(controller_saved/(1024**3), 3)} GB",
                        job_id=job_id,
                        src=display_src_path,
                        extra={
                            "saved_bytes": controller_saved,
                            "out_path": controller_out,
                            "source_deleted": bool(upload_result.get("source_deleted")),
                        },
                    )
                else:
                    try:
                        from .node_linking import local_node_info
                        local_node = local_node_info()
                    except Exception:
                        local_node = {}
                    # Persist to long-term history
                    record_encode(
                        job_id=job_id,
                        src=display_src_path,
                        out=out_path,
                        preset=preset_key,
                        src_bytes=src_bytes_i,
                        out_bytes=out_bytes,
                        duration_seconds=duration_seconds_for_stats,
                        is_hdr=bool(job.get("is_hdr", False)),
                        node_id=local_node.get("id"),
                        node_name=local_node.get("name"),
                    )

                    source_deleted = False
                    try:
                        if os.path.isfile(encode_src_path):
                            os.remove(encode_src_path)
                            source_deleted = True
                    except Exception as e:
                        log_event(
                            "job_cleanup_error",
                            f"Finished but failed to delete original: {os.path.basename(display_src_path)} ({e})",
                            level="warn",
                            job_id=job_id,
                            src=display_src_path,
                            extra={
                                "out_path": out_path,
                            },
                        )

                    log_event(
                        "job_finished",
                        f"Finished: {os.path.basename(display_src_path)} - saved {round(saved_bytes/(1024**3), 3)} GB",
                        job_id=job_id,
                        src=display_src_path,
                        extra={
                            "saved_bytes": saved_bytes,
                            "out_path": out_path,
                            "source_deleted": source_deleted,
                        },
                    )
            else:
                output_validation_error = output_reason or "output validation failed"
                job["status"] = "error"
                log_event(
                    "job_error",
                    f"Output validation failed for {os.path.basename(display_src_path)}: {output_validation_error}",
                    level="error",
                    job_id=job_id,
                    src=display_src_path,
                    extra={
                        "out_path": out_path,
                    },
                )
        except Exception as e:
            job["status"] = "error"
            output_validation_error = str(e)
            log_event(
                "stats_error",
                f"Failed to record storage savings: {e}",
                level="warn",
                job_id=job_id,
                src=display_src_path,
            )

    if job.get("status") in ("error", "canceled"):
        deleted_failed_output = False

        if out_path and not out_path_existed_before:
            try:
                if os.path.isfile(out_path):
                    os.remove(out_path)
                    deleted_failed_output = True
            except Exception as e:
                log_event(
                    "job_cleanup_error",
                    f"Failed to delete failed output: {os.path.basename(out_path)} ({e})",
                    level="warn",
                    job_id=job_id,
                    src=display_src_path,
                    extra={
                        "out_path": out_path,
                    },
                )

        if job.get("status") == "error":
            msg = f"Error: {os.path.basename(display_src_path)} (exit {ret})"
            if output_validation_error:
                msg += f" - {output_validation_error}"
            if deleted_failed_output:
                msg += " - deleted failed output"
            log_event(
                "job_error",
                msg,
                level="error",
                job_id=job_id,
                src=display_src_path,
                extra={
                    "out_path": out_path,
                    "deleted_failed_output": deleted_failed_output,
                },
            )
        elif deleted_failed_output:
            log_event(
                "job_cleanup",
                f"Canceled: deleted partial output {os.path.basename(out_path)}",
                level="warn",
                job_id=job_id,
                src=display_src_path,
                extra={
                    "out_path": out_path,
                    "deleted_failed_output": True,
                },
            )

    if job.get("status") == "canceled":
        log_event(
            "job_canceled",
            f"Canceled: {os.path.basename(display_src_path)}",
            level="warn",
            job_id=job_id,
            src=display_src_path,
        )

    # Once finished (or canceled), ETA no longer makes sense
    job["eta_seconds"] = None
    job["finished_at"] = _now_ts()
    if job.get("started_at") is not None:
        try:
            job["duration_seconds"] = max(0.0, float(job["finished_at"]) - float(job["started_at"]))
        except Exception:
            job["duration_seconds"] = None

    job["pid"] = None
    if remote_transfer:
        transfer = job.get("transfer") if isinstance(job.get("transfer"), dict) else transfer
        transfer.pop("download_token", None)
        transfer.pop("upload_token", None)
        transfer.pop("local_src", None)
        transfer.pop("work_dir", None)
        job["transfer"] = transfer
        _cleanup_transfer_work_dir(transfer_work_dir, transfer)
    _cleanup_job_preset_dir(preset_work_dir)
    save_jobs()


def dispatcher_loop():
    """
    Background worker that processes jobs from job_queue one by one.

    Behavior:
      - If queue is paused (queue_paused == True), the dispatcher idles
      - Otherwise, it finds the first job with status "queued"
      - It runs the job (run_encode), then removes it from job_queue
      - If no jobs are queued, it just sleeps briefly and checks again
    """
    global job_queue, queue_paused
    print("[DISPATCHER] started", flush=True)

    while True:
        # If queue is paused, do nothing except sleep
        if queue_paused:
            time.sleep(2.0)
            continue

        next_id = None

        # Find the first "queued" job in job_queue
        for jid in list(job_queue):
            j = jobs.get(jid)
            if not j:
                continue
            if j.get("status") == "queued":
                next_id = jid
                break

        if not next_id:
            # Nothing queued right now; idle briefly
            time.sleep(2.0)
            continue

        job = jobs.get(next_id)
        if not job:
            # Job disappeared; remove from queue and continue
            if next_id in job_queue:
                job_queue.remove(next_id)
            save_jobs()
            continue

        print(f"[DISPATCHER] starting job {next_id}", flush=True)
        run_encode(next_id, job["src"], job["preset"])
        print(f"[DISPATCHER] finished job {next_id}", flush=True)

        # Remove from queue after completion (if still present)
        if next_id in job_queue:
            job_queue.remove(next_id)
        save_jobs()


def ensure_dispatcher():
    """
    Ensure that the dispatcher thread is running (start it once).

    You can safely call this multiple times; only the first call starts
    the background thread.
    """
    global dispatcher_started
    if dispatcher_started:
        return

    t = threading.Thread(target=dispatcher_loop, daemon=True)
    t.start()
    dispatcher_started = True


# -------------------------------------------------------------------
# Queue control: pause / resume, remove, cancel, clear finished
# -------------------------------------------------------------------

def get_queue_state() -> bool:
    """
    Returns:
        bool: True if queue is paused, False if running.
    """
    return queue_paused


def set_queue_paused(paused: bool | None = None) -> bool:
    """
    Set or toggle the queue paused state.

    Args:
        paused (bool | None):
            - True/False to explicitly set state
            - None to toggle current state

    Returns:
        bool: new queue_paused value
    """
    global queue_paused

    if isinstance(paused, bool):
        queue_paused = paused
    else:
        queue_paused = not queue_paused

    save_jobs()
    log_event(
        "queue_state",
        "Queue paused" if queue_paused else "Queue resumed",
        level="info",
    )
    return queue_paused


def cancel_job(job_id: str) -> tuple[bool, str | None]:
    """
    Cancel a job.

    Behavior:
      - If job is "queued": it is removed from job_queue and marked "canceled"
      - If job is "running": SIGTERM is sent to its pid (if any), status set to "canceled"
      - Other states: still mark as canceled, but nothing else to do

    Returns:
        (ok, error_message):
            - ok = True if cancel worked
            - ok = False with error_message if job not found
    """
    global job_queue

    job = jobs.get(job_id)
    if not job:
        return False, "job not found"

    src = job.get("src")

    # Queued but not started -> remove from queue
    if job["status"] == "queued":
        if job_id in job_queue:
            try:
                job_queue.remove(job_id)
            except ValueError:
                pass
        job["status"] = "canceled"
        job["returncode"] = None
        job["progress"] = 0.0
        job["eta_seconds"] = None
        job["finished_at"] = _now_ts()
        if job.get("started_at") is not None:
            try:
                job["duration_seconds"] = max(0.0, float(job["finished_at"]) - float(job["started_at"]))
            except Exception:
                job["duration_seconds"] = None
        save_jobs()
        _src = job.get("src")
        log_event(
            "job_canceled",
            f"Canceled (queued): {os.path.basename(_src or '')}",
            level="warn",
            job_id=job_id,
            src=_src,
        )
        return True, None

    # If it's running, try to kill the process
    pid = job.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    job["status"] = "canceled"
    job["returncode"] = None
    job["progress"] = 0.0
    job["eta_seconds"] = None
    save_jobs()

    _src = job.get("src")
    log_event(
        "job_canceled",
        f"Canceled (running): {os.path.basename(_src or '')}",
        level="warn",
        job_id=job_id,
        src=_src,
    )

    return True, None




def move_queued_job(job_id: str, direction: str) -> tuple[bool, str | None]:
    """Reorder a queued job inside the queue.

    direction: up | down | top | bottom
    """
    global job_queue

    if direction not in {"up", "down", "top", "bottom"}:
        return False, "invalid direction"

    job = jobs.get(job_id)
    if not job:
        return False, "job not found"
    if job.get("status") != "queued":
        return False, "only queued jobs can be reordered"
    if job_id not in job_queue:
        return False, "job is not currently in queue"

    idx = job_queue.index(job_id)
    new_idx = idx
    if direction == "up":
        new_idx = max(0, idx - 1)
    elif direction == "down":
        new_idx = min(len(job_queue) - 1, idx + 1)
    elif direction == "top":
        new_idx = 0
    elif direction == "bottom":
        new_idx = len(job_queue) - 1

    if new_idx == idx:
        return True, None

    job_queue.pop(idx)
    job_queue.insert(new_idx, job_id)
    save_jobs()
    log_event(
        "job_reordered",
        f"Reordered queued job: {os.path.basename(job.get('src') or job_id)} → position {new_idx + 1}",
        job_id=job_id,
        src=job.get("src"),
    )
    return True, None



def move_queued_job_to_position(job_id: str, position: int) -> tuple[bool, str | None]:
    """Move a queued job to an explicit 1-based position in the queue."""
    global job_queue

    job = jobs.get(job_id)
    if not job:
        return False, "job not found"
    if job.get("status") != "queued":
        return False, "only queued jobs can be reordered"
    if job_id not in job_queue:
        return False, "job is not currently in queue"

    try:
        target_pos = int(position)
    except (TypeError, ValueError):
        return False, "invalid position"

    if target_pos < 1:
        target_pos = 1
    if target_pos > len(job_queue):
        target_pos = len(job_queue)

    idx = job_queue.index(job_id)
    new_idx = target_pos - 1
    if new_idx == idx:
        return True, None

    job_queue.pop(idx)
    job_queue.insert(new_idx, job_id)
    save_jobs()
    log_event(
        "job_reordered",
        f"Moved queued job: {os.path.basename(job.get('src') or job_id)} → position {new_idx + 1}",
        job_id=job_id,
        src=job.get("src"),
    )
    return True, None


def get_job_summary() -> dict:
    """Return lightweight dashboard metrics for the jobs page."""
    archived = _normalize_dashboard_totals(dashboard_totals)
    status_counts = {
        "queued": 0,
        "running": 0,
        "done": int(archived.get("done") or 0),
        "error": int(archived.get("error") or 0),
        "canceled": int(archived.get("canceled") or 0),
    }
    active_error_count = 0
    total_saved_bytes = int(archived.get("saved_bytes") or 0)
    live_done_runtime_seconds = 0.0
    live_error_runtime_seconds = 0.0
    live_canceled_runtime_seconds = 0.0

    for job in jobs.values():
        status = str(job.get("status") or "").lower()
        if status in status_counts:
            status_counts[status] += 1
        if status == "error":
            active_error_count += 1

        try:
            total_saved_bytes += int(job.get("saved_bytes") or 0)
        except Exception:
            pass

        try:
            duration_seconds = float(job.get("duration_seconds") or 0.0)
        except Exception:
            duration_seconds = 0.0
        if status == "done":
            live_done_runtime_seconds += duration_seconds
        elif status == "error":
            live_error_runtime_seconds += duration_seconds
        elif status == "canceled":
            live_canceled_runtime_seconds += duration_seconds

    try:
        storage_summary = get_storage_summary()
    except Exception:
        storage_summary = {}

    try:
        storage_saved_bytes = int(storage_summary.get("saved_bytes") or 0)
        total_saved_bytes = max(total_saved_bytes, storage_saved_bytes)
    except Exception:
        pass

    try:
        storage_runtime_seconds = float(storage_summary.get("total_runtime_seconds") or 0.0)
    except Exception:
        storage_runtime_seconds = 0.0

    done_runtime_seconds = max(
        storage_runtime_seconds,
        float(archived.get("done_runtime_seconds") or 0.0) + live_done_runtime_seconds,
    )
    total_runtime_seconds = (
        done_runtime_seconds
        + float(archived.get("error_runtime_seconds") or 0.0)
        + float(archived.get("canceled_runtime_seconds") or 0.0)
        + live_error_runtime_seconds
        + live_canceled_runtime_seconds
    )

    try:
        status_counts["done"] = max(status_counts["done"], int(storage_summary.get("count") or 0))
    except Exception:
        pass

    queued_items = [jid for jid in job_queue if jid in jobs and jobs[jid].get("status") == "queued"]
    running_job_id = next((jid for jid, j in jobs.items() if j.get("status") == "running"), None)

    return {
        "counts": status_counts,
        "queue_paused": bool(queue_paused),
        "queued_count": len(queued_items),
        "running_job_id": running_job_id,
        "active_error_count": active_error_count,
        "saved_bytes": total_saved_bytes,
        "saved_gb": round(total_saved_bytes / (1024**3), 3) if total_saved_bytes else 0.0,
        "total_runtime_seconds": round(total_runtime_seconds, 1),
    }

def remove_queued_job(job_id: str) -> tuple[bool, str | None]:
    """
    Remove a job entirely from the queue *only if* it is still "queued".

    Used by the "Remove from queue" button in the UI.

    Returns:
        (ok, error_message):
            - ok = True if job removed
            - ok = False with error_message if job not found / not queued
    """
    global job_queue

    job = jobs.get(job_id)
    if not job:
        return False, "job not found"

    src = job.get("src")

    if job.get("status") != "queued":
        return False, "can only remove jobs in 'queued' status"

    if job_id in job_queue:
        try:
            job_queue.remove(job_id)
        except ValueError:
            pass

    jobs.pop(job_id, None)
    save_jobs()
    _src = job.get("src")
    log_event(
        "job_removed",
        f"Removed from queue: {os.path.basename(_src or '')}",
        level="info",
        job_id=job_id,
        src=_src,
    )
    return True, None


def clear_finished_jobs() -> int:
    """
    Remove all jobs that are finished: status in {"done", "error"}.

    - Does NOT touch queued or running jobs
    - Deletes the log files corresponding to removed jobs

    Returns:
        int: number of jobs removed
    """
    global jobs, job_queue, dashboard_totals

    to_remove = []
    for jid, j in list(jobs.items()):
        if j.get("status") in ("done", "error"):
            to_remove.append(jid)

    archived = _normalize_dashboard_totals(dashboard_totals)
    removed = 0
    for jid in to_remove:
        job = jobs.get(jid) or {}
        status = str(job.get("status") or "").lower()
        if status in ("done", "error"):
            archived[status] = int(archived.get(status) or 0) + 1
        try:
            duration_seconds = float(job.get("duration_seconds") or 0.0)
        except Exception:
            duration_seconds = 0.0
        try:
            archived["saved_bytes"] = int(archived.get("saved_bytes") or 0) + int(job.get("saved_bytes") or 0)
        except Exception:
            pass
        try:
            archived["runtime_seconds"] = float(archived.get("runtime_seconds") or 0.0) + duration_seconds
        except Exception:
            pass
        if status == "done":
            archived["done_runtime_seconds"] = float(archived.get("done_runtime_seconds") or 0.0) + duration_seconds
        elif status == "error":
            archived["error_runtime_seconds"] = float(archived.get("error_runtime_seconds") or 0.0) + duration_seconds

        # Remove from jobs dict
        jobs.pop(jid, None)
        removed += 1

        # Make sure it's not in the queue
        if jid in job_queue:
            try:
                job_queue.remove(jid)
            except ValueError:
                pass

        # Remove log file if present
        log_path = os.path.join(LOG_DIR, f"{jid}.log")
        try:
            os.remove(log_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[WARN] Failed to remove log for {jid}: {e}", flush=True)

    dashboard_totals = archived
    save_jobs()
    return removed


def clear_error_status() -> int:
    """Remove error jobs and reset archived error counts so the app status can return to idle."""
    global jobs, job_queue, dashboard_totals

    archived = _normalize_dashboard_totals(dashboard_totals)
    cleared = int(archived.get("error") or 0)
    archived["error"] = 0
    archived["error_runtime_seconds"] = 0.0

    for jid, job in list(jobs.items()):
        if str(job.get("status") or "").lower() != "error":
            continue
        jobs.pop(jid, None)
        cleared += 1
        if jid in job_queue:
            try:
                job_queue.remove(jid)
            except ValueError:
                pass
        log_path = os.path.join(LOG_DIR, f"{jid}.log")
        try:
            os.remove(log_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[WARN] Failed to remove error log for {jid}: {e}", flush=True)

    dashboard_totals = archived
    save_jobs()
    return cleared

def clear_queued_jobs() -> int:
    """
    Remove all jobs that are currently queued (status == "queued").

    - Does NOT touch running jobs
    - Does NOT touch done / error / canceled jobs (those are history)
    - Also removes them from job_queue
    - Logs are removed if they exist (usually they won't for queued jobs)

    Returns:
        int: number of jobs removed
    """
    global jobs, job_queue

    to_remove: list[str] = []
    for jid, j in list(jobs.items()):
        if j.get("status") == "queued":
            to_remove.append(jid)

    removed = 0
    for jid in to_remove:
        # Remove from jobs dict
        jobs.pop(jid, None)
        removed += 1

        # Make sure it's not in the queue
        if jid in job_queue:
            try:
                job_queue.remove(jid)
            except ValueError:
                pass

        # Remove log file if present (probably rare for queued jobs)
        log_path = os.path.join(LOG_DIR, f"{jid}.log")
        try:
            os.remove(log_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[WARN] Failed to remove log for queued job {jid}: {e}", flush=True)

    save_jobs()
    return removed
