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

from .config import (
    DATA_DIR,
    LOG_DIR,
    JOBS_FILE,
    VIDEO_EXTS,
    ALLOWED_PREFIXES,
)
from .presets import resolve_preset_file_and_name
from .settings import load_settings  # pull in global settings (hb_threads, etc.)

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

# Regex to parse HandBrakeCLI progress lines:
# e.g. "Encoding: task 1 of 1, 42.34 % (118.19 fps, avg 118.40 fps, ETA 00h02m34s)"
PROGRESS_RE = re.compile(
    r"Encoding:\s+task\s+\d+\s+of\s+\d+,\s*([\d\.]+)\s*%"
)

# Regex to extract the ETA substring from a line.
# It is intentionally loose: it just grabs the token after "ETA",
# e.g. "00h02m34s", "03m21s", "00:03:21"
ETA_RE = re.compile(r"ETA\s+([0-9hms:]+)")


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


# -------------------------------------------------------------------
# Persistence: saving / loading jobs.json
# -------------------------------------------------------------------

def save_jobs():
    """
    Persist current job metadata + queue + queue_paused flag to disk.

    Writes a JSON file to JOBS_FILE. We intentionally do NOT persist pids,
    because the OS process won't survive container restarts anyway.
    """
    global queue_paused

    try:
        serializable = {}
        for jid, j in jobs.items():
            serializable[jid] = {
                "status": j.get("status"),
                "src": j.get("src"),
                "preset": j.get("preset"),
                "extra_args": j.get("extra_args", ""),
                "log": j.get("log", ""),
                "returncode": j.get("returncode"),
                "pid": None,  # never persist the actual pid
                "progress": float(j.get("progress") or 0.0),
                # NEW: persist ETA if present
                "eta_seconds": j.get("eta_seconds"),
            }

        state = {
            "jobs": serializable,
            "queue": list(job_queue),
            "queue_paused": queue_paused,
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
    global jobs, job_queue, queue_paused

    if not os.path.isfile(JOBS_FILE):
        jobs = {}
        job_queue = []
        queue_paused = False
        return

    try:
        with open(JOBS_FILE, "r") as f:
            state = json.load(f)

        data = state.get("jobs") or {}
        q = state.get("queue") or []
        queue_paused = bool(state.get("queue_paused", False))

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
                "log": j.get("log", ""),
                "returncode": j.get("returncode"),
                "pid": None,
                "progress": float(j.get("progress") or 0.0),
                # NEW: restore ETA if it was saved
                "eta_seconds": j.get("eta_seconds"),
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

def create_job(src: str, preset: str, extra_args: str = "") -> str:
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
        "log": "",
        "returncode": None,
        "pid": None,
        "progress": 0.0,
        "eta_seconds": None,  # if you already added ETA support
    }
    job_queue.append(job_id)
    save_jobs()
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
            "log": "",
            "returncode": None,
            "pid": None,
            "progress": 0.0,
            "eta_seconds": None,  # remove if you don't use ETA
        }
        job_queue.append(job_id)
        count += 1

    if count > 0:
        save_jobs()
        ensure_dispatcher()

    return count



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
                "status": j.get("status"),
                "returncode": j.get("returncode"),
                "progress": float(j.get("progress") or 0.0),
                "eta_seconds": eta_val,
                "has_log": has_log,
            }
        )

    # Sort newest first (by job id, which is a uuid; you could later swap to timestamp)
    job_items.sort(key=lambda x: x["id"], reverse=True)
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
    job["status"] = "running"
    job["progress"] = 0.0
    job["eta_seconds"] = None  # reset ETA at the start
    save_jobs()

    # ------------------------------------------------------------
    # ENVIRONMENT SETUP FOR WORKER SCRIPT
    # - SRC: path to source video (always required)
    # - HB_PRESET_FILE / HB_PRESET_NAME: resolved from preset key
    # - HB_THREADS: optional override from settings.py (Settings page)
    # ------------------------------------------------------------
    env = os.environ.copy()
    env["SRC"] = src_path  # encode-one.sh uses this

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

    # Once finished (or canceled), ETA no longer makes sense
    job["eta_seconds"] = None

    job["pid"] = None
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
        save_jobs()
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

    return True, None


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

    if job.get("status") != "queued":
        return False, "can only remove jobs in 'queued' status"

    if job_id in job_queue:
        try:
            job_queue.remove(job_id)
        except ValueError:
            pass

    jobs.pop(job_id, None)
    save_jobs()
    return True, None


def clear_finished_jobs() -> int:
    """
    Remove all jobs that are finished: status in {"done", "error"}.

    - Does NOT touch queued or running jobs
    - Deletes the log files corresponding to removed jobs

    Returns:
        int: number of jobs removed
    """
    global jobs, job_queue

    to_remove = []
    for jid, j in list(jobs.items()):
        if j.get("status") in ("done", "error"):
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

        # Remove log file if present
        log_path = os.path.join(LOG_DIR, f"{jid}.log")
        try:
            os.remove(log_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[WARN] Failed to remove log for {jid}: {e}", flush=True)

    save_jobs()
    return removed

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


