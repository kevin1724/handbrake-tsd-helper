"""
Flask route definitions for HandBrake TSD Helper.

This module:
- Defines all HTTP endpoints (API + web UI)
- Uses helpers from jobs.py and presets.py
- Renders the single-page Web UI (index.html template)

NOTES FOR FUTURE MAINTAINERS
---------------------------
This file historically accumulated multiple partial implementations of the same
"HandBrake scan JSON" parsing logic. The Size Wizard depends on a reliable probe
(duration / width / height / fps). HandBrakeCLI is a bit quirky:
- It may print JSON to *stderr* (not stdout)
- It may print other log lines before/after the JSON
- It may print multiple JSON values in the same run (objects or arrays)
So we:
1) capture stdout+stderr
2) extract *all* JSON values safely (brace/bracket matching)
3) find the value that contains TitleList/Titles (sometimes nested)
4) choose the best title (valid geometry + longest duration)
5) if JSON still lacks geometry/duration, fall back to parsing text scan output


Implementation notes:
- We run a short HandBrakeCLI encode (e.g., 8–12 seconds) into a temp file,
  using the same preset base (1080/4k/auto -> preset_config mapping) plus
  wizard args (--target-size, --encoder-preset, optional downscale).
- We return base64 JPEGs so the web UI can render them directly.
"""

import os
import json
import math
import re
import subprocess
import base64
import tempfile
import uuid
import signal
import time
import hashlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


from flask import (
    request,
    jsonify,
    render_template,
    send_file,
    abort,
)
from werkzeug.utils import secure_filename

from .config import (
    ROOTS,
    VIDEO_EXTS,
    PRESET_DIR,
    LOG_DIR,
    DATA_DIR,
)
from .jobs import (
    is_allowed_path,
    create_job,
    create_jobs_batch,
    get_job,
    list_jobs_for_api,
    cancel_job,
    remove_queued_job,
    clear_finished_jobs as clear_finished_jobs_core,
    clear_queued_jobs,
    get_queue_state,
    set_queue_paused,
    move_queued_job_to_position,
    move_queued_job,
    get_job_summary,
)

from .presets import (
    list_preset_files,
    preset_config,
    save_preset_config,
    guess_preset_from_filename,
)
from .settings import (
    load_settings,
    save_settings,
)

from .cpu_profiles import (
    list_cpu_profiles,
    get_cpu_profile,
)

from .events import load_events, clear_events
from .storage_stats import get_summary as get_storage_summary, list_encodes as list_storage_encodes, clear_stats as clear_storage_stats

# -------------------------------------------------------------------
# Media probing + preview estimation helpers
# -------------------------------------------------------------------

def _run_cmd(cmd):
    """Run a command and return (ok, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return (p.returncode == 0, p.stdout, p.stderr)
    except FileNotFoundError:
        return (False, "", f"not found: {cmd[0]}")
    except Exception as e:
        return (False, "", str(e))

PREVIEW_PID_DIR = "/tmp"

def _preview_pidfile(preview_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", (preview_id or ""))
    return os.path.join(PREVIEW_PID_DIR, f"hbwiz_{safe}.pgid")

def _kill_preview_by_id(preview_id: str) -> bool:
    """Kill a running HandBrake preview process group by preview_id."""
    path = _preview_pidfile(preview_id)
    if not preview_id or not os.path.isfile(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            pgid = int((f.read() or "").strip() or "0")
        if pgid <= 0:
            return False

        # Try graceful, then hard kill
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        time.sleep(0.25)

        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def _extract_all_json_values(text: str):
    """
    Extract ALL JSON values from an arbitrary string using bracket/brace matching.

    Why:
    - HandBrakeCLI may output multiple JSON values
    - JSON can be an object {...} OR an array [...]
    - It may include non-JSON logs before/after
    - Naively slicing from first '{' to last '}' often includes extra text and breaks json.loads

    Returns: list[str] of JSON blobs (each blob is a standalone JSON value)
    """
    results = []
    i = 0
    n = len(text)

    while i < n:
        # Find next potential JSON start
        next_obj = text.find("{", i)
        next_arr = text.find("[", i)

        if next_obj == -1 and next_arr == -1:
            break

        if next_obj == -1:
            start = next_arr
            open_ch, close_ch = "[", "]"
        elif next_arr == -1:
            start = next_obj
            open_ch, close_ch = "{", "}"
        else:
            if next_obj < next_arr:
                start = next_obj
                open_ch, close_ch = "{", "}"
            else:
                start = next_arr
                open_ch, close_ch = "[", "]"

        depth = 0
        in_str = False
        escape = False

        for j in range(start, n):
            ch = text[j]

            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue

            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    results.append(text[start:j + 1])
                    i = j + 1
                    break
        else:
            # ran out of text without closing
            break

    return results


def _find_title_list(obj):
    """Find a TitleList/Titles list in common HandBrake JSON shapes."""
    if not isinstance(obj, dict):
        return None

    # Most common recent format
    if isinstance(obj.get("TitleList"), list):
        return obj["TitleList"]
    if isinstance(obj.get("Titles"), list):
        return obj["Titles"]

    # Sometimes nested
    scan = obj.get("Scan")
    if isinstance(scan, dict):
        if isinstance(scan.get("TitleList"), list):
            return scan["TitleList"]
        if isinstance(scan.get("Titles"), list):
            return scan["Titles"]

    # Sometimes nested under Result
    res = obj.get("Result")
    if isinstance(res, dict):
        tl = _find_title_list(res)
        if tl is not None:
            return tl

    return None


def _parse_duration_seconds(t: dict) -> float:
    """
    Parse duration in seconds from a HandBrake title dict.

    HandBrake JSON is not consistent across versions. Duration can be:
    - dict with Hours/Minutes/Seconds/Ticks
    - dict with Seconds or seconds
    - number
    - string timecode "HH:MM:SS(.sss)" or "MM:SS(.sss)"
    - sometimes top-level keys like DurationSeconds
    """
    d = t.get("Duration")

    # Dict form
    if isinstance(d, dict):
        try:
            hours = float(d.get("Hours", d.get("hours", 0)) or 0)
            minutes = float(d.get("Minutes", d.get("minutes", 0)) or 0)
            seconds = float(d.get("Seconds", d.get("seconds", 0)) or 0)
            ticks = float(d.get("Ticks", d.get("ticks", 0)) or 0)

            dur = hours * 3600 + minutes * 60 + seconds
            if ticks and ticks > 0:
                dur += (ticks / 10000000.0)  # typical HB tick scale

            if dur > 0:
                return dur
        except Exception:
            pass

    # Numeric seconds
    if isinstance(d, (int, float)):
        try:
            dur = float(d)
            if dur > 0:
                return dur
        except Exception:
            pass

    # String timecode
    if isinstance(d, str) and d.strip():
        s = d.strip()
        parts = s.split(":")
        try:
            if len(parts) == 3:
                hh = float(parts[0])
                mm = float(parts[1])
                ss = float(parts[2])
                dur = hh * 3600 + mm * 60 + ss
                if dur > 0:
                    return dur
            elif len(parts) == 2:
                mm = float(parts[0])
                ss = float(parts[1])
                dur = mm * 60 + ss
                if dur > 0:
                    return dur
        except Exception:
            pass

    # Fallback keys sometimes present
    for k in ("Seconds", "seconds", "duration", "DurationSeconds", "duration_sec"):
        if k in t:
            try:
                dur = float(t.get(k))
                if dur > 0:
                    return dur
            except Exception:
                pass

    return 0.0


def _extract_whfps(vdict: dict):
    """
    Extract width/height/fps/codec from a dict that *might* represent video fields.
    Supports Geometry/Video/Stream variations.
    """
    w = (
        vdict.get("Width") or vdict.get("width") or
        vdict.get("PixelWidth") or vdict.get("pixel_width")
    )
    h = (
        vdict.get("Height") or vdict.get("height") or
        vdict.get("PixelHeight") or vdict.get("pixel_height")
    )

    try:
        w = int(w or 0)
        h = int(h or 0)
    except Exception:
        w, h = 0, 0

    fps = vdict.get("FrameRate") or vdict.get("fps") or vdict.get("FrameRateNum")
    if isinstance(fps, dict):
        fps = fps.get("Rate") or fps.get("rate")

    try:
        fps_val = float(fps or 0.0)
    except Exception:
        fps_val = 0.0

    codec = (
        vdict.get("CodecName") or vdict.get("Codec") or
        vdict.get("codec") or vdict.get("VideoCodec") or None
    )

    return w, h, fps_val, codec


def _extract_title_video_info(title: dict):
    """
    Extract duration / width / height / fps / codec from a *title object*.

    Priority:
    1) title.Geometry + title.FrameRate + title.Duration  (most common and most reliable)
    2) title.Video
    3) title.Streams / title.StreamList
    """
    dur = _parse_duration_seconds(title)

    # Geometry (best source of width/height)
    w = h = 0
    geo = title.get("Geometry")
    if isinstance(geo, dict):
        gw, gh, _g_fps, _g_codec = _extract_whfps(geo)
        w, h = gw, gh

    # FrameRate at title-level
    fps = 0.0
    fr = title.get("FrameRate")
    if isinstance(fr, dict):
        try:
            fps = float(fr.get("Rate") or fr.get("rate") or 0.0)
        except Exception:
            fps = 0.0
    elif isinstance(fr, (int, float, str)):
        try:
            fps = float(fr)
        except Exception:
            fps = 0.0

    codec = None

    # Video dict
    v = title.get("Video")
    if isinstance(v, dict):
        vw, vh, vfps, vcodec = _extract_whfps(v)
        if w <= 0 and vw > 0:
            w = vw
        if h <= 0 and vh > 0:
            h = vh
        if fps <= 0 and vfps > 0:
            fps = vfps
        if not codec and vcodec:
            codec = vcodec

    # Streams / StreamList
    streams = title.get("Streams") or title.get("StreamList")
    if isinstance(streams, list):
        for s in streams:
            if not isinstance(s, dict):
                continue
            if s.get("Type") == "Video" or s.get("Codec") or s.get("Width") or s.get("Height"):
                sw, sh, sfps, scodec = _extract_whfps(s)
                if w <= 0 and sw > 0:
                    w = sw
                if h <= 0 and sh > 0:
                    h = sh
                if fps <= 0 and sfps > 0:
                    fps = sfps
                if not codec and scodec:
                    codec = scodec
                break

    return dur, w, h, fps, codec



def _ffprobe_media_fast(src_path: str):
    """
    Fast probe using ffprobe (much faster than HandBrake scan).
    Returns: dict with duration_sec, width, height, fps
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "format=duration:stream=width,height,r_frame_rate,pix_fmt,color_space,color_transfer,color_primaries,side_data_list",
        "-of", "json",
        src_path,
    ]
    ok, out, err = _run_cmd(cmd)
    if not ok or not out.strip():
        raise RuntimeError(f"ffprobe failed: {(err or out or '').strip()[:400]}")

    j = json.loads(out)
    fmt = (j.get("format") or {})
    streams = (j.get("streams") or [])
    v0 = streams[0] if streams else {}

    duration_sec = float(fmt.get("duration") or 0.0)
    width = int(v0.get("width") or 0)
    height = int(v0.get("height") or 0)

    # r_frame_rate like "24000/1001"
    fps = 0.0
    rfr = v0.get("r_frame_rate") or ""
    if isinstance(rfr, str) and "/" in rfr:
        num, den = rfr.split("/", 1)
        try:
            fps = float(num) / float(den)
        except Exception:
            fps = 0.0
    else:
        try:
            fps = float(rfr or 0.0)
        except Exception:
            fps = 0.0

    if duration_sec <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("ffprobe returned incomplete video info")

    is_hdr, hdr_reason = _detect_hdr_from_video_info(v0, src_path)

    return {
        "duration_sec": duration_sec,
        "width": width,
        "height": height,
        "fps": fps or 24.0,
        "is_hdr": is_hdr,
        "hdr_reason": hdr_reason,
    }


def _probe_media_text_fallback(src_path: str):
    """
    LAST RESORT fallback if JSON is present but missing duration/geometry.

    This runs a normal scan and tries to regex out:
    - duration
    - resolution

    This is intentionally permissive so the Size Wizard preview still works.
    """
    ok, out, err = _run_cmd(["HandBrakeCLI", "--scan", "-i", src_path])
    raw = ((out or "") + "\n" + (err or "")).strip()
    if not raw:
        raise RuntimeError("HandBrake scan returned no output (fallback)")

    # duration patterns
    dur_sec = 0.0
    m = re.search(r"duration:\s*(\d+):(\d+):(\d+)", raw, re.IGNORECASE)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3))
        dur_sec = float(hh * 3600 + mm * 60 + ss)
    else:
        m2 = re.search(r"duration:\s*(\d+):(\d+)", raw, re.IGNORECASE)
        if m2:
            mm = int(m2.group(1))
            ss = int(m2.group(2))
            dur_sec = float(mm * 60 + ss)

    # resolution patterns
    w = h = 0
    m3 = re.search(r"size:\s*(\d+)\s*x\s*(\d+)", raw, re.IGNORECASE)
    if m3:
        w = int(m3.group(1))
        h = int(m3.group(2))
    else:
        # last ditch: first reasonable NxM pattern
        m4 = re.search(r"(\d{3,5})\s*x\s*(\d{3,5})", raw)
        if m4:
            w = int(m4.group(1))
            h = int(m4.group(2))

    fps = 24.0  # fallback

    if dur_sec <= 0 or w <= 0 or h <= 0:
        snippet = raw[:600].replace("\n", "\\n")
        raise RuntimeError(f"HandBrake scan JSON incomplete (fallback failed). Output snippet: {snippet}")

    return {
        "duration_sec": float(dur_sec),
        "width": int(w),
        "height": int(h),
        "fps": float(fps),
        "video_codec": None,
    }


def _probe_media(src_path):
    """
    Probe using HandBrakeCLI scan JSON.

    This is the canonical probe used by:
    - /probe
    - /wizard_preview
    - /encode_wizard
    - /wizard_preview_images

    Strategy:
    1) Run --scan --json and capture stdout+stderr
    2) Extract all JSON values (objects/arrays)
    3) Find TitleList/Titles (possibly nested)
    4) Choose best title (valid geometry + longest duration)
    5) If JSON exists but still missing duration/geometry, fall back to text scan
    """
    ok, out, err = _run_cmd(["HandBrakeCLI", "--scan", "--json", "-i", src_path])

    raw = ((out or "") + "\n" + (err or "")).strip()
    if not raw:
        raise RuntimeError("HandBrake scan returned no output")

    json_blobs = _extract_all_json_values(raw)
    if not json_blobs:
        snippet = raw[:600].replace("\n", "\\n")
        raise RuntimeError(f"HandBrake scan JSON incomplete (no JSON found). Output snippet: {snippet}")

    scan_obj = None

    # Find a JSON value that contains TitleList/Titles
    for blob in json_blobs:
        try:
            candidate = json.loads(blob)
        except Exception:
            continue

        # Sometimes the top-level value is an array of objects
        if isinstance(candidate, list):
            for item in candidate:
                tl = _find_title_list(item)
                if isinstance(tl, list) and len(tl) > 0:
                    scan_obj = item
                    break
            if scan_obj is not None:
                break

        # Most common: object containing TitleList
        tl = _find_title_list(candidate)
        if isinstance(tl, list) and len(tl) > 0:
            scan_obj = candidate
            break

    if scan_obj is None:
        raise RuntimeError("HandBrake scan JSON missing TitleList/Titles")

    title_list = _find_title_list(scan_obj) or []

    # Choose best title
    best = None
    best_score = -1.0

    for t in title_list:
        if not isinstance(t, dict):
            continue

        dur, w, h, fps, codec = _extract_title_video_info(t)

        # Score: prefer valid geometry, then longer duration
        score = 0.0
        if w > 0 and h > 0:
            score += 1_000_000.0
        score += dur

        if score > best_score:
            best_score = score
            best = (dur, w, h, fps, codec)

    if not best:
        return _probe_media_text_fallback(src_path)

    dur, w, h, fps, codec = best
    fps = fps or 24.0

    if dur <= 0 or w <= 0 or h <= 0:
        # JSON exists but doesn't expose these fields in our parseable shape
        return _probe_media_text_fallback(src_path)

    hdr_reason = _hdr_filename_reason(src_path)
    return {
        "duration_sec": float(dur),
        "width": int(w),
        "height": int(h),
        "fps": float(fps),
        "video_codec": codec,
        "is_hdr": bool(hdr_reason),
        "hdr_reason": hdr_reason,
    }


def _size_to_mb(value, unit):
    u = (unit or "MB").upper()
    v = float(value)
    return v * (1024.0 if u == "GB" else 1.0)


def _quality_audio_kbps(quality):
    q = (quality or "balanced").lower()
    if q == "high":
        return 256
    if q == "small":
        return 128
    return 192


def _preset_from_quality(quality):
    q = (quality or "balanced").lower()
    if q == "high":
        return "slow"
    if q == "small":
        return "fast"
    return "medium"


def _estimate_encode_fps(width, height, enc_preset):
    """Rough FPS estimates on a 'generic' modern CPU for x265.

    These are heuristics until we add job-history learning.
    """
    p = (enc_preset or "medium").lower()
    megapixels = (width * height) / 1_000_000.0 if width and height else 2.0

    base_1080 = 35.0

    mult = 1.0
    if p == "slow":
        mult = 0.65
    elif p == "fast":
        mult = 1.6

    fps = base_1080 * mult * (2.0 / max(megapixels, 0.5))
    return max(2.0, min(fps, 120.0))


def _bpp(video_bitrate_kbps, width, height, fps):
    if not video_bitrate_kbps or not width or not height or not fps:
        return 0.0
    return (video_bitrate_kbps * 1000.0) / (width * height * fps)


def _quality_label_from_bpp(bpp):
    if bpp >= 0.08:
        return ("good", "🟢 Good")
    if bpp >= 0.045:
        return ("ok", "🟡 OK / Streaming")
    return ("risky", "🔴 Risky (likely artifacts)")


WIZARD_PRESETS_FILE = os.path.join(DATA_DIR, "wizard_presets.json")
WIZARD_PRESET_LIMIT = 100

WIZARD_VIDEO_CODECS = {"h265", "h264"}
WIZARD_ENCODER_FAMILIES = {"software", "qsv"}
WIZARD_BIT_DEPTHS = {"8", "10"}
WIZARD_QUALITIES = {"high", "balanced", "small"}
WIZARD_ENCODER_SPEEDS = {"auto", "fast", "medium", "slow"}
WIZARD_RESOLUTION_MODES = {"auto", "keep", "2160", "1440", "1080", "720"}
WIZARD_AUDIO_MODES = {"auto", "aac", "copy"}
WIZARD_AUDIO_TRACKS = {"first", "all"}
WIZARD_SUBTITLE_MODES = {"none", "first", "all"}
WIZARD_FRAMERATE_MODES = {"same", "pfr", "cfr"}
WIZARD_FRAMERATES = {"23.976", "24", "25", "29.97", "30", "50", "59.94", "60"}
WIZARD_DEINTERLACE_MODES = {"off", "decomb", "yadif"}
WIZARD_CROP_MODES = {"auto", "none"}
WIZARD_AI_GOALS = {"balanced", "quality", "speed", "small", "archive"}
WIZARD_AI_HARDWARE = {"auto", "software", "qsv"}
WIZARD_AI_TRACK_SCOPES = {"first", "all"}
WIZARD_AI_SUBTITLE_SCOPES = {"none", "first", "all"}

WIZARD_DEFAULT_OPTIONS = {
    "ai_mode": False,
    "ai_goal": "balanced",
    "ai_hardware": "auto",
    "ai_copy_audio": True,
    "ai_audio_scope": "all",
    "ai_subtitle_scope": "all",
    "audio_languages": ["eng", "spa"],
    "subtitle_languages": ["eng", "spa"],
    "preset": "auto",
    "target_size_auto": True,
    "target_size_value": 5.0,
    "target_size_unit": "GB",
    "quality": "balanced",
    "video_codec": "h265",
    "encoder_family": "software",
    "bit_depth": "10",
    "encoder_speed": "auto",
    "resolution_mode": "auto",
    "audio_mode": "copy",
    "audio_bitrate": "auto",
    "audio_tracks": "all",
    "subtitle_mode": "all",
    "framerate_mode": "same",
    "framerate": "23.976",
    "deinterlace": "off",
    "crop_mode": "auto",
    "two_pass": False,
}

WIZARD_SOURCE_TARGETS = {
    "movie": {"label": "Movie", "target_size_value": 5.0, "target_size_unit": "GB", "target_mb": 5120.0},
    "show": {"label": "Show", "target_size_value": 800.0, "target_size_unit": "MB", "target_mb": 800.0},
}

WIZARD_SHOW_PATTERNS = [
    re.compile(r"(?:^|[ ._\-\[\(])s\d{1,2}e\d{1,3}(?:\D|$)", re.IGNORECASE),
    re.compile(r"(?:^|[ ._\-\[\(])\d{1,2}x\d{1,3}(?:\D|$)", re.IGNORECASE),
    re.compile(r"(?:^|[ ._\-\[\(])season[ ._\-]*\d+", re.IGNORECASE),
    re.compile(r"(?:^|[ ._\-\[\(])episode[ ._\-]*\d+", re.IGNORECASE),
]


def _choice(value, allowed: set[str], default: str) -> str:
    val = str(value or default).strip().lower()
    return val if val in allowed else default


def _truthy(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


WIZARD_LANGUAGE_ALIASES = {
    "en": "eng",
    "english": "eng",
    "eng": "eng",
    "ja": "jpn",
    "jp": "jpn",
    "japanese": "jpn",
    "jpn": "jpn",
    "es": "spa",
    "spanish": "spa",
    "spa": "spa",
    "fr": "fre",
    "french": "fre",
    "fre": "fre",
    "fra": "fre",
    "de": "ger",
    "german": "ger",
    "ger": "ger",
    "deu": "ger",
    "it": "ita",
    "italian": "ita",
    "ita": "ita",
    "pt": "por",
    "portuguese": "por",
    "por": "por",
    "ko": "kor",
    "korean": "kor",
    "kor": "kor",
    "zh": "chi",
    "chinese": "chi",
    "chi": "chi",
    "zho": "chi",
    "nl": "dut",
    "dutch": "dut",
    "dut": "dut",
    "nld": "dut",
    "ru": "rus",
    "russian": "rus",
    "rus": "rus",
    "pl": "pol",
    "polish": "pol",
    "pol": "pol",
    "und": "und",
    "unknown": "und",
}


def _wizard_languages(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = " ".join(str(v) for v in value)
    else:
        raw = str(value)

    out = []
    seen = set()
    for part in re.split(r"[,;/\s]+", raw.strip().lower()):
        if not part:
            continue
        token = WIZARD_LANGUAGE_ALIASES.get(part, part)
        token = re.sub(r"[^a-z0-9]", "", token)[:3]
        if len(token) != 3 or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= 12:
            break
    return out


def _wizard_source_target(kind: str) -> dict:
    target = WIZARD_SOURCE_TARGETS.get(kind) or WIZARD_SOURCE_TARGETS["movie"]
    return {
        "label": target["label"],
        "target_size_value": target["target_size_value"],
        "target_size_unit": target["target_size_unit"],
        "target_mb": target["target_mb"],
    }


def _wizard_detect_source_type(src_path: str, duration_sec=None) -> dict:
    base = os.path.basename(src_path or "")
    lower_base = base.lower()
    lower_path = (src_path or "").replace("\\", "/").lower()
    path_parts = [part for part in re.split(r"[\\/]+", lower_path) if part]

    for pattern in WIZARD_SHOW_PATTERNS:
        if pattern.search(lower_base):
            target = _wizard_source_target("show")
            return {"kind": "show", "reason": "episode filename pattern", **target}

    if any(part in {"tv", "tv shows", "shows", "show", "series", "seasons"} for part in path_parts):
        target = _wizard_source_target("show")
        return {"kind": "show", "reason": "show folder path", **target}

    if any(part in {"movie", "movies", "film", "films"} for part in path_parts):
        target = _wizard_source_target("movie")
        return {"kind": "movie", "reason": "movie folder path", **target}

    try:
        duration = float(duration_sec or 0.0)
    except Exception:
        duration = 0.0

    if 0 < duration <= 75 * 60:
        target = _wizard_source_target("show")
        return {"kind": "show", "reason": "runtime under 75 minutes", **target}

    target = _wizard_source_target("movie")
    reason = "runtime over 75 minutes" if duration > 0 else "default"
    return {"kind": "movie", "reason": reason, **target}


def _wizard_apply_source_target(options: dict, source_type: dict) -> dict:
    if not options.get("target_size_auto"):
        return options
    out = options.copy()
    out["target_size_value"] = source_type["target_size_value"]
    out["target_size_unit"] = source_type["target_size_unit"]
    return out


def _wizard_encoder_label(encoder_name: str) -> str:
    labels = {
        "x264": "H.264 CPU",
        "x265": "H.265 CPU",
        "x265_10bit": "H.265 10-bit CPU",
        "qsv_h264": "H.264 Intel QSV",
        "qsv_h265": "H.265 Intel QSV",
        "qsv_h265_10bit": "H.265 10-bit Intel QSV",
    }
    return labels.get(encoder_name, encoder_name)


def _wizard_encoder_name(options: dict) -> str:
    codec = options["video_codec"]
    family = options["encoder_family"]
    bit_depth = options["bit_depth"]

    if family == "qsv":
        if codec == "h264":
            return "qsv_h264"
        return "qsv_h265_10bit" if bit_depth == "10" else "qsv_h265"

    if codec == "h264":
        return "x264"
    return "x265_10bit" if bit_depth == "10" else "x265"


def _wizard_encoder_preset(options: dict) -> str:
    speed = options["encoder_speed"]
    quality = options["quality"]
    family = options["encoder_family"]

    if speed == "auto":
        speed = "slow" if quality == "high" else ("fast" if quality == "small" else "medium")

    if family == "qsv":
        return {"fast": "speed", "medium": "balanced", "slow": "quality"}.get(speed, "balanced")
    return {"fast": "fast", "medium": "medium", "slow": "slow"}.get(speed, "medium")


def _wizard_audio_kbps(options: dict) -> int:
    if options["audio_mode"] == "copy":
        return 256
    if options["audio_bitrate"] != "auto":
        try:
            return max(64, min(640, int(options["audio_bitrate"])))
        except Exception:
            pass
    return _quality_audio_kbps(options["quality"])


def _scale_to_height(width: int, height: int, target_height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0 or target_height <= 0 or height <= target_height:
        return width, height
    scale = target_height / float(height)
    out_w = int((width * scale) // 2 * 2)
    out_h = int((height * scale) // 2 * 2)
    return max(2, out_w), max(2, out_h)


def _wizard_likely_qsv(cpu_label: str) -> bool:
    label = (cpu_label or "").lower()
    if "intel" not in label:
        return False
    return "no igpu" not in label and "kf" not in label


def _wizard_ai_choices(options: dict, cpu, cpu_override: float, src_w: int, src_h: int, duration_sec: float) -> tuple[dict, list[str]]:
    if not options.get("ai_mode"):
        return options, []

    out = options.copy()
    goal = out["ai_goal"]
    hw = out["ai_hardware"]
    cpu_score = max(0.1, float(getattr(cpu, "speed_index", 1.0)) * float(cpu_override or 1.0))
    qsv_ok = hw == "qsv" or (hw == "auto" and _wizard_likely_qsv(getattr(cpu, "label", "")))
    weak_cpu = cpu_score < 0.75
    strong_cpu = cpu_score >= 1.35
    very_strong_cpu = cpu_score >= 2.0
    is_4k = src_h >= 1800 or src_w >= 3200
    notes = []

    if hw == "software":
        out["encoder_family"] = "software"
    elif hw == "qsv":
        out["encoder_family"] = "qsv"
    elif goal == "speed" and qsv_ok:
        out["encoder_family"] = "qsv"
    elif weak_cpu and qsv_ok:
        out["encoder_family"] = "qsv"
    else:
        out["encoder_family"] = "software"

    if goal == "speed":
        out["quality"] = "small"
        out["video_codec"] = "h265" if out["encoder_family"] == "qsv" else ("h264" if weak_cpu else "h265")
        out["encoder_speed"] = "fast"
        out["resolution_mode"] = "1080" if is_4k and weak_cpu else "auto"
        notes.append("speed-first choices")
    elif goal == "small":
        out["quality"] = "small"
        out["video_codec"] = "h265"
        out["encoder_speed"] = "slow" if out["encoder_family"] == "software" and strong_cpu else "medium"
        out["resolution_mode"] = "auto"
        notes.append("smaller-file choices")
    elif goal == "quality":
        out["quality"] = "high"
        out["video_codec"] = "h265"
        out["encoder_speed"] = "slow" if out["encoder_family"] == "software" and strong_cpu else "medium"
        out["resolution_mode"] = "keep" if (not is_4k or very_strong_cpu) else "auto"
        notes.append("quality-first choices")
    elif goal == "archive":
        out["quality"] = "balanced"
        out["video_codec"] = "h265"
        out["encoder_speed"] = "slow" if out["encoder_family"] == "software" and very_strong_cpu else "medium"
        out["resolution_mode"] = "auto"
        notes.append("archive choices")
    else:
        out["quality"] = "balanced"
        out["video_codec"] = "h265"
        out["encoder_speed"] = "medium" if out["encoder_family"] == "software" else "auto"
        out["resolution_mode"] = "auto"
        notes.append("balanced choices")

    out["bit_depth"] = "8" if out["video_codec"] == "h264" else "10"
    out["two_pass"] = (
        out["encoder_family"] == "software"
        and goal in {"quality", "small", "archive"}
        and cpu_score >= 1.0
        and duration_sec <= 4 * 60 * 60
    )

    out["audio_mode"] = "copy" if out["ai_copy_audio"] else "aac"
    if out["audio_mode"] == "copy":
        out["audio_bitrate"] = "auto"
        notes.append("audio copy")
    elif goal == "quality":
        out["audio_bitrate"] = "256"
    elif goal in {"small", "speed"}:
        out["audio_bitrate"] = "160"
    else:
        out["audio_bitrate"] = "192"

    out["audio_tracks"] = out["ai_audio_scope"] if out["audio_languages"] else "first"
    out["subtitle_mode"] = out["ai_subtitle_scope"] if out["subtitle_languages"] else "none"
    out["framerate_mode"] = "same"
    out["deinterlace"] = "off"
    out["crop_mode"] = "auto"

    notes.append(f"CPU profile {getattr(cpu, 'label', 'default')} at x{cpu_score:.2f}")
    notes.append(f"{out['encoder_family'].upper()} {out['video_codec'].upper()} {out['encoder_speed']}")
    if out["audio_languages"]:
        notes.append("audio languages " + ", ".join(out["audio_languages"]))
    if out["subtitle_languages"]:
        notes.append("subtitle languages " + ", ".join(out["subtitle_languages"]))
    return out, notes


def _wizard_normalize_options(data: dict) -> dict:
    data = data or {}
    options = WIZARD_DEFAULT_OPTIONS.copy()
    audio_language_value = data["audio_languages"] if "audio_languages" in data else options["audio_languages"]
    subtitle_language_value = data["subtitle_languages"] if "subtitle_languages" in data else options["subtitle_languages"]

    preset = _choice(data.get("preset"), {"1080", "4k", "auto"}, options["preset"])
    unit = str(data.get("target_size_unit") or options["target_size_unit"]).strip().upper()
    if unit not in {"MB", "GB"}:
        raise ValueError("invalid target_size_unit")

    try:
        size_value = float(data.get("target_size_value") or options["target_size_value"])
    except Exception:
        raise ValueError("invalid target_size_value")
    if size_value <= 0:
        raise ValueError("invalid target_size_value")

    options.update(
        {
            "ai_mode": _truthy(data.get("ai_mode"), options["ai_mode"]),
            "ai_goal": _choice(data.get("ai_goal"), WIZARD_AI_GOALS, options["ai_goal"]),
            "ai_hardware": _choice(data.get("ai_hardware"), WIZARD_AI_HARDWARE, options["ai_hardware"]),
            "ai_copy_audio": _truthy(data.get("ai_copy_audio"), options["ai_copy_audio"]),
            "ai_audio_scope": _choice(data.get("ai_audio_scope"), WIZARD_AI_TRACK_SCOPES, options["ai_audio_scope"]),
            "ai_subtitle_scope": _choice(data.get("ai_subtitle_scope"), WIZARD_AI_SUBTITLE_SCOPES, options["ai_subtitle_scope"]),
            "audio_languages": _wizard_languages(audio_language_value),
            "subtitle_languages": _wizard_languages(subtitle_language_value),
            "preset": preset,
            "target_size_auto": _truthy(data.get("target_size_auto"), options["target_size_auto"]),
            "target_size_value": size_value,
            "target_size_unit": unit,
            "quality": _choice(data.get("quality"), WIZARD_QUALITIES, options["quality"]),
            "video_codec": _choice(data.get("video_codec"), WIZARD_VIDEO_CODECS, options["video_codec"]),
            "encoder_family": _choice(data.get("encoder_family"), WIZARD_ENCODER_FAMILIES, options["encoder_family"]),
            "bit_depth": _choice(data.get("bit_depth"), WIZARD_BIT_DEPTHS, options["bit_depth"]),
            "encoder_speed": _choice(data.get("encoder_speed"), WIZARD_ENCODER_SPEEDS, options["encoder_speed"]),
            "audio_mode": _choice(data.get("audio_mode"), WIZARD_AUDIO_MODES, options["audio_mode"]),
            "audio_tracks": _choice(data.get("audio_tracks"), WIZARD_AUDIO_TRACKS, options["audio_tracks"]),
            "subtitle_mode": _choice(data.get("subtitle_mode"), WIZARD_SUBTITLE_MODES, options["subtitle_mode"]),
            "framerate_mode": _choice(data.get("framerate_mode"), WIZARD_FRAMERATE_MODES, options["framerate_mode"]),
            "framerate": _choice(data.get("framerate"), WIZARD_FRAMERATES, options["framerate"]),
            "deinterlace": _choice(data.get("deinterlace"), WIZARD_DEINTERLACE_MODES, options["deinterlace"]),
            "crop_mode": _choice(data.get("crop_mode"), WIZARD_CROP_MODES, options["crop_mode"]),
            "two_pass": _truthy(data.get("two_pass"), options["two_pass"]),
        }
    )

    audio_bitrate = str(data.get("audio_bitrate") or options["audio_bitrate"]).strip().lower()
    if audio_bitrate != "auto":
        try:
            audio_bitrate_i = int(audio_bitrate)
        except Exception:
            audio_bitrate_i = 192
        audio_bitrate = str(max(64, min(640, audio_bitrate_i)))
    options["audio_bitrate"] = audio_bitrate

    resolution_mode = data.get("resolution_mode")
    if not resolution_mode:
        force_4k = _truthy(data.get("force_4k"), False)
        allow_downscale = _truthy(data.get("allow_downscale"), True)
        resolution_mode = "keep" if force_4k or not allow_downscale else "auto"
    options["resolution_mode"] = _choice(resolution_mode, WIZARD_RESOLUTION_MODES, options["resolution_mode"])

    return options


def _wizard_resolution_decision(options: dict, src_w: int, src_h: int, fps: float, video_kbps: float):
    mode = options["resolution_mode"]
    out_w, out_h = src_w, src_h
    decision = "keep"
    note = ""

    if mode == "keep":
        return out_w, out_h, decision, note

    if mode in {"720", "1080", "1440", "2160"}:
        target_h = int(mode)
        if src_h > target_h:
            out_w, out_h = _scale_to_height(src_w, src_h, target_h)
            decision = f"cap_{target_h}"
            note = f"Resolution capped at {target_h}p."
        return out_w, out_h, decision, note

    bpp_src = _bpp(video_kbps, src_w, src_h, fps)
    cand_w, cand_h = _scale_to_height(src_w, src_h, 1080)
    bpp_1080 = _bpp(video_kbps, cand_w, cand_h, fps) if (cand_w, cand_h) != (src_w, src_h) else bpp_src

    if src_h > 1080 and bpp_src < 0.045 and bpp_1080 >= bpp_src * 1.6:
        out_w, out_h = cand_w, cand_h
        decision = "auto_downscale"
        note = "Auto downscale selected to protect quality at the requested size."

    return out_w, out_h, decision, note


def _wizard_build_extra_args(options: dict, video_kbps: float, out_w: int, out_h: int, src_w: int, src_h: int, *, preview: bool = False) -> list[str]:
    args = [
        "-b",
        str(int(video_kbps)),
        "--encoder",
        _wizard_encoder_name(options),
        "--encoder-preset",
        _wizard_encoder_preset(options),
    ]

    if (out_w, out_h) != (src_w, src_h):
        args += ["--width", str(int(out_w)), "--height", str(int(out_h))]

    if options["framerate_mode"] in {"pfr", "cfr"}:
        args += ["-r", options["framerate"], f"--{options['framerate_mode']}"]

    if options["deinterlace"] == "decomb":
        args.append("--decomb")
    elif options["deinterlace"] == "yadif":
        args.append("--deinterlace")

    if options["crop_mode"] == "none":
        args += ["--crop", "0:0:0:0"]

    if not preview:
        audio_langs = options.get("audio_languages") or []
        subtitle_langs = options.get("subtitle_languages") or []

        if audio_langs:
            args += ["--audio-lang-list", ",".join(audio_langs)]

        if options["audio_tracks"] == "all":
            args.append("--all-audio")
        elif audio_langs:
            args.append("--first-audio")

        if options["audio_mode"] == "copy":
            args += ["-E", "copy"]
        else:
            args += ["-E", "av_aac", "-B", str(_wizard_audio_kbps(options))]

        if subtitle_langs:
            args += ["--subtitle-lang-list", ",".join(subtitle_langs)]

        if options["subtitle_mode"] == "first":
            if subtitle_langs:
                args.append("--first-subtitle")
            else:
                args += ["--subtitle", "1"]
        elif options["subtitle_mode"] == "all":
            args.append("--all-subtitles")

        if options["subtitle_mode"] != "none":
            args.append("--subtitle-burned=none")

        if options["two_pass"] and options["encoder_family"] == "software":
            args.append("--two-pass")

    return args


def _wizard_plan(data: dict, *, probe_func=_probe_media, for_queue: bool = False, preview: bool = False) -> dict:
    src = (data.get("src") or "").strip()
    if not src or not os.path.isfile(src):
        raise ValueError("invalid src")
    if not is_allowed_path(src):
        raise ValueError("path not allowed")

    base = os.path.basename(src)
    name_only, _ext = os.path.splitext(base)
    if for_queue and name_only.lower().endswith("-tsd"):
        raise ValueError("file already tagged -TSD, not queuing")

    options = _wizard_normalize_options(data)
    effective_preset = options["preset"]
    if effective_preset == "auto":
        effective_preset = guess_preset_from_filename(base)

    info = dict(probe_func(src) or {})
    source_size_bytes = int(os.path.getsize(src))
    info["source_size_bytes"] = source_size_bytes
    info["source_size_mb"] = round(source_size_bytes / (1024.0 * 1024.0), 2)
    filename_hdr_reason = _hdr_filename_reason(src)
    info["is_hdr"] = bool(info.get("is_hdr") or filename_hdr_reason)
    if info["is_hdr"] and not info.get("hdr_reason"):
        info["hdr_reason"] = filename_hdr_reason or "filename"
    duration_sec = float(info.get("duration_sec") or 0.0)
    src_w = int(info.get("width") or 0)
    src_h = int(info.get("height") or 0)
    fps = float(info.get("fps") or 0.0) or 24.0
    if duration_sec <= 0 or src_w <= 0 or src_h <= 0:
        raise RuntimeError("probe incomplete")

    source_type = _wizard_detect_source_type(src, duration_sec)
    options = _wizard_apply_source_target(options, source_type)
    info["source_type"] = source_type["kind"]
    info["source_type_label"] = source_type["label"]
    info["source_type_reason"] = source_type["reason"]

    settings = load_settings()
    cpu = get_cpu_profile(settings.get("cpu_profile"))
    try:
        cpu_override_f = float(settings.get("cpu_speed_override", 1.0))
    except Exception:
        cpu_override_f = 1.0
    if cpu_override_f <= 0:
        cpu_override_f = 1.0

    options, ai_notes = _wizard_ai_choices(options, cpu, cpu_override_f, src_w, src_h, duration_sec)
    target_mb = _size_to_mb(options["target_size_value"], options["target_size_unit"])
    target_bytes = target_mb * 1024.0 * 1024.0
    total_bitrate_kbps = (target_bytes * 8.0 / duration_sec) / 1000.0
    audio_kbps = _wizard_audio_kbps(options)
    video_kbps = max(250.0, total_bitrate_kbps - audio_kbps)
    out_w, out_h, decision, note = _wizard_resolution_decision(options, src_w, src_h, fps, video_kbps)
    bpp_final = _bpp(video_kbps, out_w, out_h, fps)
    q_code, q_label = _quality_label_from_bpp(bpp_final)

    encoder_preset = _wizard_encoder_preset(options)
    encoder_name = _wizard_encoder_name(options)
    extra_args = _wizard_build_extra_args(options, video_kbps, out_w, out_h, src_w, src_h, preview=preview)

    base_est_fps = _estimate_encode_fps(out_w, out_h, encoder_preset)
    if options["encoder_family"] == "qsv":
        base_est_fps *= 3.0
    if info.get("is_hdr"):
        base_est_fps *= 0.88
    est_fps = max(1.0, min(base_est_fps * float(cpu.speed_index) * cpu_override_f, 500.0))
    eta_sec = (duration_sec * fps) / est_fps if est_fps > 0 else 0.0
    history_prediction = _history_prediction_for(source_size_bytes, effective_preset, bool(info.get("is_hdr")))

    return {
        "src": src,
        "preset": effective_preset,
        "options": options,
        "probe": info,
        "extra_args": extra_args,
        "inputs": {
            "target_mb": target_mb,
            **options,
        },
        "estimates": {
            "total_bitrate_kbps": round(total_bitrate_kbps, 1),
            "audio_bitrate_kbps": audio_kbps,
            "video_bitrate_kbps": round(video_kbps, 1),
            "bpp": round(bpp_final, 5),
            "quality_code": q_code,
            "quality_label": q_label,
            "encoder": encoder_name,
            "encoder_label": _wizard_encoder_label(encoder_name),
            "encoder_preset": encoder_preset,
            "ai_mode": bool(options.get("ai_mode")),
            "ai_summary": "; ".join(ai_notes),
            "ai_decisions": ai_notes,
            "source_type": source_type,
            "target_size_auto": bool(options.get("target_size_auto")),
            "eta_seconds": int(round(eta_sec)),
            "eta_human": f"{int(eta_sec//3600)}h {int((eta_sec%3600)//60)}m" if eta_sec >= 3600 else f"{int(eta_sec//60)}m",
            "history_prediction": history_prediction,
            "cpu_profile": cpu.id,
            "cpu_label": cpu.label,
            "cpu_speed_index": float(cpu.speed_index),
            "cpu_speed_override": float(cpu_override_f),
            "est_fps": round(est_fps, 1),
            "decision": decision,
            "decision_note": note,
            "output_resolution": {"width": out_w, "height": out_h},
        },
    }


def _wizard_public_options(options: dict) -> dict:
    normalized = _wizard_normalize_options(options)
    if isinstance(options, dict) and "target_size_auto" not in options and "target_size_value" in options:
        normalized["target_size_auto"] = False
    return normalized


def _load_wizard_presets() -> list[dict]:
    try:
        with open(WIZARD_PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[WARN] Failed to load wizard_presets.json: {e}", flush=True)
        return []

    rows = data if isinstance(data, list) else []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            options = _wizard_public_options(row.get("options") or {})
        except Exception:
            options = WIZARD_DEFAULT_OPTIONS.copy()
        out.append(
            {
                "id": str(row.get("id") or uuid.uuid4()),
                "name": str(row.get("name") or "Wizard preset"),
                "options": options,
                "created_at": float(row.get("created_at") or time.time()),
                "updated_at": float(row.get("updated_at") or row.get("created_at") or time.time()),
            }
        )
    out.sort(key=lambda r: (r["name"].lower(), r["updated_at"]))
    return out[:WIZARD_PRESET_LIMIT]


def _save_wizard_presets(rows: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WIZARD_PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(rows[:WIZARD_PRESET_LIMIT], f, indent=2)


def _clean_wizard_preset_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"\s+", " ", value)
    if not value:
        raise ValueError("missing preset name")
    return value[:80]


BETA_LIBRARY_CACHE_FILE = os.path.join(DATA_DIR, "beta_library_cache.json")
BETA_TRACKED_SHOWS_FILE = os.path.join(DATA_DIR, "beta_tracked_shows.json")
BETA_POSTER_CACHE: dict[tuple, dict] = {}
BETA_MEDIA_TAG_RE = re.compile(
    r"(?<!\w)(480p|576p|720p|1080p|2160p|4320p|4k|8k|uhd|hdr10\+|hdr10plus|hdr10|hdr|hlg|dv|dovi|dolby ?vision|"
    r"bluray|blu-ray|brrip|webrip|web-dl|webdl|hdtv|remux|proper|repack|"
    r"x264|x265|h264|h265|hevc|av1|aac|ac3|eac3|e-ac3|ddp|ddplus|dd\+|dts|truehd|atmos|"
    r"extended|unrated|directors? ?cut|theatrical)(?!\w)",
    re.IGNORECASE,
)
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
HDR_VIDEO_HINT_RE = re.compile(r"(?:^|[ ._\-\[\(])(?:hevc|x265|h[ ._\-]*265|main[ ._\-]*10|10[ ._\-]*bit)(?=$|[ ._\-\]\)])", re.IGNORECASE)
HDR_TENBIT_HINT_RE = re.compile(r"(?:^|[ ._\-\[\(])(?:main[ ._\-]*10|10[ ._\-]*bit)(?=$|[ ._\-\]\)])", re.IGNORECASE)
HDR_AUDIO_HINT_RE = re.compile(r"(?:^|[ ._\-\[\(])(?:ddp(?:[ ._\-]*[257]\.?1)?|dd\+|e[ ._\-]*ac3|eac3|atmos|truehd)(?=$|[ ._\-\]\)])", re.IGNORECASE)


def _hdr_filename_reason(path: str) -> str:
    text = f"{os.path.basename(path or '')} {path or ''}"
    direct = HDR_PATH_RE.search(text)
    if direct:
        return f"filename: {direct.group(0).strip(' ._-[]()').lower()}"

    has_size = bool(HDR_SIZE_HINT_RE.search(text))
    has_remux = bool(HDR_REMUX_HINT_RE.search(text))
    has_video = bool(HDR_VIDEO_HINT_RE.search(text))
    has_tenbit = bool(HDR_TENBIT_HINT_RE.search(text))
    has_audio = bool(HDR_AUDIO_HINT_RE.search(text))

    if has_size and (has_remux or has_video or has_audio):
        return "filename: 4k release tags"
    if has_remux and has_tenbit:
        return "filename: remux 10-bit tags"
    return ""


def _path_looks_hdr(path: str) -> bool:
    return bool(_hdr_filename_reason(path))


def _detect_hdr_from_video_info(stream: dict, path: str = "") -> tuple[bool, str]:
    stream = stream if isinstance(stream, dict) else {}
    transfer = str(stream.get("color_transfer") or "").lower()
    primaries = str(stream.get("color_primaries") or "").lower()
    color_space = str(stream.get("color_space") or "").lower()
    pix_fmt = str(stream.get("pix_fmt") or "").lower()
    side_data = stream.get("side_data_list") if isinstance(stream.get("side_data_list"), list) else []
    side_text = json.dumps(side_data).lower() if side_data else ""

    if transfer in {"smpte2084", "arib-std-b67"}:
        return True, transfer
    if "mastering display metadata" in side_text or "content light level" in side_text:
        return True, "hdr metadata"
    if "bt2020" in primaries or "bt2020" in color_space:
        return True, "bt2020"
    filename_reason = _hdr_filename_reason(path)
    if "p010" in pix_fmt and filename_reason:
        return True, "10-bit hdr filename"
    if filename_reason:
        return True, filename_reason
    return False, ""


def _median(values: list[float]) -> float | None:
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return float(values[mid])
    return (float(values[mid - 1]) + float(values[mid])) / 2.0


def _history_prediction_model() -> dict:
    jobs_by_id = {row.get("id"): row for row in list_jobs_for_api()}
    buckets: dict[tuple[str, object], list[dict]] = {}

    for row in list_storage_encodes(limit=5000):
        if not isinstance(row, dict):
            continue
        try:
            src_bytes = int(row.get("src_bytes") or 0)
            out_bytes = int(row.get("out_bytes") or 0)
        except Exception:
            continue
        if src_bytes <= 0 or out_bytes <= 0:
            continue

        job = jobs_by_id.get(row.get("job_id")) or {}
        preset = str(row.get("preset") or job.get("preset") or "").strip().lower()
        if preset not in {"1080", "4k"}:
            preset = guess_preset_from_filename(os.path.basename(row.get("src") or ""))

        duration_seconds = row.get("duration_seconds")
        if duration_seconds is None:
            duration_seconds = job.get("duration_seconds")
        try:
            duration_seconds = float(duration_seconds or 0.0)
        except Exception:
            duration_seconds = 0.0

        is_hdr = row.get("is_hdr")
        if is_hdr is None:
            is_hdr = job.get("is_hdr")
        filename_hdr = _path_looks_hdr(str(row.get("src") or row.get("out") or ""))
        is_hdr = bool(is_hdr) or filename_hdr

        out_ratio = out_bytes / float(src_bytes)
        if out_ratio <= 0 or out_ratio > 2.0:
            continue

        src_gb = src_bytes / float(1024**3)
        sample = {
            "preset": preset,
            "is_hdr": is_hdr,
            "out_ratio": out_ratio,
            "saved_ratio": max(0.0, (src_bytes - out_bytes) / float(src_bytes)),
            "seconds_per_gb": (duration_seconds / src_gb) if duration_seconds > 0 and src_gb > 0 else None,
        }

        for key in ((preset, is_hdr), (preset, None), ("any", is_hdr), ("any", None)):
            buckets.setdefault(key, []).append(sample)

    return {"buckets": buckets}


def _history_stats_from_samples(samples: list[dict]) -> dict | None:
    if not samples:
        return None
    out_ratio = _median([float(s.get("out_ratio") or 0.0) for s in samples])
    saved_ratio = _median([float(s.get("saved_ratio") or 0.0) for s in samples])
    seconds_per_gb = _median([
        float(s.get("seconds_per_gb") or 0.0)
        for s in samples
        if s.get("seconds_per_gb")
    ])
    if out_ratio is None:
        return None
    return {
        "sample_count": len(samples),
        "runtime_sample_count": len([s for s in samples if s.get("seconds_per_gb")]),
        "out_ratio": max(0.01, min(1.5, float(out_ratio))),
        "saved_ratio": max(0.0, min(1.0, float(saved_ratio or 0.0))),
        "seconds_per_gb": seconds_per_gb,
    }


def _history_prediction_for(src_bytes: int, preset: str, is_hdr: bool, model: dict | None = None) -> dict:
    try:
        src_bytes_i = int(src_bytes or 0)
    except Exception:
        src_bytes_i = 0
    if src_bytes_i <= 0:
        return {"available": False, "sample_count": 0, "reason": "missing source size"}

    preset_key = preset if preset in {"1080", "4k"} else "1080"
    model = model or _history_prediction_model()
    buckets = model.get("buckets") or {}
    match = "none"
    stats = None
    for key, label in (
        ((preset_key, bool(is_hdr)), "preset+hdr"),
        ((preset_key, None), "preset"),
        (("any", bool(is_hdr)), "hdr"),
        (("any", None), "all"),
    ):
        stats = _history_stats_from_samples(buckets.get(key) or [])
        if stats:
            match = label
            break

    if not stats:
        return {"available": False, "sample_count": 0, "reason": "not enough history", "preset": preset_key, "is_hdr": bool(is_hdr)}

    estimated_out = int(round(src_bytes_i * stats["out_ratio"]))
    estimated_saved = max(0, src_bytes_i - estimated_out)
    src_gb = src_bytes_i / float(1024**3)
    estimated_runtime = None
    if stats.get("seconds_per_gb"):
        estimated_runtime = int(round(src_gb * float(stats["seconds_per_gb"])))

    sample_count = int(stats.get("sample_count") or 0)
    confidence = "low"
    if match == "preset+hdr" and sample_count >= 8:
        confidence = "high"
    elif match in {"preset+hdr", "preset"} and sample_count >= 3:
        confidence = "medium"

    return {
        "available": True,
        "preset": preset_key,
        "is_hdr": bool(is_hdr),
        "match": match,
        "confidence": confidence,
        "sample_count": sample_count,
        "runtime_sample_count": int(stats.get("runtime_sample_count") or 0),
        "estimated_out_bytes": estimated_out,
        "estimated_saved_bytes": estimated_saved,
        "estimated_runtime_seconds": estimated_runtime,
        "out_ratio": round(float(stats["out_ratio"]), 4),
        "saved_ratio": round(float(stats.get("saved_ratio") or 0.0), 4),
    }


def _combine_history_predictions(predictions: list[dict], total_size_bytes: int = 0) -> dict:
    usable = [p for p in predictions if isinstance(p, dict) and p.get("available")]
    if not usable:
        return {"available": False, "sample_count": 0, "reason": "not enough history"}

    estimated_out = sum(int(p.get("estimated_out_bytes") or 0) for p in usable)
    estimated_saved = sum(int(p.get("estimated_saved_bytes") or 0) for p in usable)
    runtime_values = [p.get("estimated_runtime_seconds") for p in usable if p.get("estimated_runtime_seconds") is not None]
    total_runtime = sum(int(v or 0) for v in runtime_values) if runtime_values else None
    sample_count = sum(int(p.get("sample_count") or 0) for p in usable)

    return {
        "available": True,
        "confidence": "medium" if len(usable) >= 3 else "low",
        "sample_count": sample_count,
        "items_predicted": len(usable),
        "items_total": len(predictions),
        "estimated_out_bytes": estimated_out,
        "estimated_saved_bytes": estimated_saved if estimated_saved else max(0, int(total_size_bytes or 0) - estimated_out),
        "estimated_runtime_seconds": total_runtime,
    }


def _beta_mapped_roots(settings=None) -> list[dict]:
    settings = settings or load_settings()
    folders = settings.get("beta_media_folders") or {}
    out = []
    seen = set()

    for kind, prefix in (("movies", "Movies"), ("shows", "Shows")):
        rows = folders.get(kind) if isinstance(folders, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "").strip()
            if not path:
                continue
            key = os.path.normcase(os.path.realpath(path))
            if key in seen:
                continue
            seen.add(key)
            label = str(row.get("label") or "").strip() or os.path.basename(path.rstrip("/\\")) or prefix
            out.append({"path": path, "label": f"{prefix}: {label}", "kind": kind})

    return out


def _beta_roots_payload(settings=None) -> list[dict]:
    return _beta_mapped_roots(settings)


def _beta_root_is_mapped(root_path: str, settings=None) -> bool:
    target = os.path.normcase(os.path.realpath(root_path or ""))
    return any(os.path.normcase(os.path.realpath(row["path"])) == target for row in _beta_mapped_roots(settings))


def _beta_empty_library(settings=None) -> dict:
    settings = settings or {}
    return {
        "scope": "empty",
        "root": "",
        "roots": [],
        "recursive": True,
        "generated_at": 0,
        "stats": {
            "movies": 0,
            "shows": 0,
            "episodes": 0,
            "scanned": 0,
            "skipped_tsd": 0,
            "limited": False,
        },
        "tmdb_configured": bool(_beta_tmdb_config(settings)),
        "movies": [],
        "shows": [],
    }


def _beta_empty_tracking() -> dict:
    return {"shows": {}, "updated_at": 0}


def _beta_show_tracking_key(show: dict) -> str:
    show = show if isinstance(show, dict) else {}
    existing = str(show.get("id") or show.get("show_id") or "").strip()
    if existing:
        return existing
    key = f"{str(show.get('title') or 'Unknown Title').strip().lower()}::{show.get('year') or ''}"
    return uuid.uuid5(uuid.NAMESPACE_DNS, key).hex


def _beta_show_paths(show: dict) -> list[str]:
    show = show if isinstance(show, dict) else {}
    paths = []
    for ep in show.get("files") or []:
        if isinstance(ep, dict) and ep.get("path"):
            paths.append(str(ep.get("path")))
    if not paths and show.get("path"):
        paths.append(str(show.get("path")))
    return sorted(set(paths))


def _beta_clean_path_list(paths) -> list[str]:
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list):
        return []
    cleaned = []
    seen = set()
    for raw in paths:
        path = str(raw or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        cleaned.append(path)
    return cleaned


def _beta_load_tracking() -> dict:
    try:
        with open(BETA_TRACKED_SHOWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _beta_empty_tracking()
    except Exception as e:
        print(f"[WARN] Failed to load beta tracked shows: {e}", flush=True)
        return _beta_empty_tracking()

    if not isinstance(data, dict):
        return _beta_empty_tracking()

    rows = data.get("shows") if isinstance(data.get("shows"), dict) else {}
    cleaned = {}
    for key, row in rows.items():
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or key or "").strip()
        if not row_id:
            continue
        known_paths = _beta_clean_path_list(row.get("known_paths"))
        cleaned[row_id] = {
            "id": row_id,
            "title": str(row.get("title") or "Unknown Title"),
            "year": row.get("year"),
            "tmdb_id": row.get("tmdb_id"),
            "poster_url": str(row.get("poster_url") or ""),
            "tracked": bool(row.get("tracked", True)),
            "known_paths": known_paths,
            "created_at": float(row.get("created_at") or 0),
            "updated_at": float(row.get("updated_at") or 0),
        }

    return {
        "shows": cleaned,
        "updated_at": float(data.get("updated_at") or 0),
    }


def _beta_save_tracking(data: dict) -> None:
    data = data if isinstance(data, dict) else _beta_empty_tracking()
    data["updated_at"] = time.time()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BETA_TRACKED_SHOWS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _beta_apply_tracking(data: dict, tracking: dict | None = None) -> dict:
    data = data if isinstance(data, dict) else {}
    tracking = tracking if isinstance(tracking, dict) else _beta_load_tracking()
    tracked_rows = tracking.get("shows") if isinstance(tracking.get("shows"), dict) else {}
    tracked_count = 0
    pending_count = 0

    for show in data.get("shows") or []:
        if not isinstance(show, dict):
            continue
        show_id = _beta_show_tracking_key(show)
        row = tracked_rows.get(show_id) or {}
        paths = set(_beta_show_paths(show))
        known = set(_beta_clean_path_list(row.get("known_paths")))
        is_tracked = bool(row.get("tracked")) if row else False
        new_paths = sorted(path for path in paths if path not in known)

        show["tracked"] = is_tracked
        show["tracking"] = {
            "tracked": is_tracked,
            "known_episode_count": len(paths & known),
            "new_episode_count": len(new_paths) if is_tracked else 0,
            "new_paths": new_paths if is_tracked else [],
            "updated_at": row.get("updated_at") if row else 0,
        }
        if is_tracked:
            tracked_count += 1
            pending_count += len(new_paths)

    data["tracking"] = {
        "tracked_count": tracked_count,
        "new_episode_count": pending_count,
        "updated_at": float(tracking.get("updated_at") or 0),
    }
    return data


def _beta_auto_queue_tracked_episodes(data: dict, tracking: dict) -> dict:
    result = {
        "detected_count": 0,
        "queued_count": 0,
        "skipped": [],
    }
    tracking = tracking if isinstance(tracking, dict) else _beta_empty_tracking()
    tracked_rows = tracking.get("shows") if isinstance(tracking.get("shows"), dict) else {}
    changed = False

    for show in data.get("shows") or []:
        if not isinstance(show, dict):
            continue
        show_id = _beta_show_tracking_key(show)
        row = tracked_rows.get(show_id)
        if not isinstance(row, dict) or not row.get("tracked"):
            continue

        current_paths = _beta_show_paths(show)
        known = set(_beta_clean_path_list(row.get("known_paths")))
        new_paths = [path for path in current_paths if path not in known]
        if not new_paths:
            row["known_paths"] = sorted(set(current_paths) | known)
            continue

        result["detected_count"] += len(new_paths)
        to_create = []
        for path in new_paths:
            reason = ""
            if not os.path.isfile(path):
                reason = "not a file"
            elif not is_allowed_path(path):
                reason = "path not allowed"
            elif not path.lower().endswith(VIDEO_EXTS):
                reason = "not a video"
            elif os.path.splitext(os.path.basename(path))[0].lower().endswith("-tsd"):
                reason = "already tagged -TSD"

            if reason:
                result["skipped"].append({"path": path, "reason": reason})
                continue
            to_create.append((path, guess_preset_from_filename(os.path.basename(path))))

        if to_create:
            result["queued_count"] += int(create_jobs_batch(to_create) or 0)

        row["known_paths"] = sorted(set(current_paths) | known)
        row["title"] = show.get("title") or row.get("title") or "Unknown Title"
        row["year"] = show.get("year")
        row["tmdb_id"] = show.get("tmdb_id") or row.get("tmdb_id")
        row["poster_url"] = show.get("poster_url") or row.get("poster_url") or ""
        row["updated_at"] = time.time()
        changed = True

    if changed:
        tracking["shows"] = tracked_rows
    return result


def _beta_load_library_cache(settings=None) -> dict:
    settings = settings or {}
    try:
        with open(BETA_LIBRARY_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _beta_empty_library(settings)
    except Exception as e:
        print(f"[WARN] Failed to load beta library cache: {e}", flush=True)
        return _beta_empty_library(settings)

    if not isinstance(data, dict):
        return _beta_empty_library(settings)

    data.setdefault("movies", [])
    data.setdefault("shows", [])
    data.setdefault("stats", {})
    data["tmdb_configured"] = bool(_beta_tmdb_config(settings))
    return _beta_apply_tracking(_beta_refresh_predictions(data), _beta_load_tracking())


def _beta_save_library_cache(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BETA_LIBRARY_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _beta_clear_library_cache() -> None:
    try:
        os.remove(BETA_LIBRARY_CACHE_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[WARN] Failed to clear beta library cache: {e}", flush=True)


def _beta_clean_title(value: str) -> str:
    text = os.path.splitext(os.path.basename(value or ""))[0]
    text = re.sub(r"[-_.]+", " ", text)
    text = re.sub(r"\bTSD\b$", " ", text, flags=re.IGNORECASE)
    text = BETA_MEDIA_TAG_RE.sub(" ", text)
    text = re.sub(r"[\[\]\(\)\{\}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -._")
    return text or "Unknown Title"


def _beta_title_from_path(src_path: str, title_part: str, media_type: str) -> str:
    if title_part and len(title_part.strip()) >= 2:
        return _beta_clean_title(title_part)

    parent = os.path.basename(os.path.dirname(src_path))
    grandparent = os.path.basename(os.path.dirname(os.path.dirname(src_path)))
    parent_l = parent.lower()

    if media_type == "show":
        if re.search(r"season\s*\d+|^s\d+$", parent_l, re.IGNORECASE) and grandparent:
            return _beta_clean_title(grandparent)
        if parent:
            return _beta_clean_title(parent)

    return _beta_clean_title(os.path.basename(src_path))


def _beta_parse_media(src_path: str) -> dict:
    filename = os.path.basename(src_path)
    name_only, _ext = os.path.splitext(filename)
    source_type = _wizard_detect_source_type(src_path)
    media_type = "show" if source_type["kind"] == "show" else "movie"

    season = episode = None
    title_part = name_only
    show_match = re.search(r"(?i)(?:^|[ ._\-\[\(])s(\d{1,2})e(\d{1,3})(?:\D|$)", name_only)
    if not show_match:
        show_match = re.search(r"(?i)(?:^|[ ._\-\[\(])(\d{1,2})x(\d{1,3})(?:\D|$)", name_only)
    if show_match:
        media_type = "show"
        season = int(show_match.group(1))
        episode = int(show_match.group(2))
        title_part = name_only[: show_match.start()]

    year = None
    year_match = re.search(r"(?:^|[ ._\-\[\(])((?:19|20)\d{2})(?:\D|$)", name_only)
    if year_match:
        year = int(year_match.group(1))
        if media_type == "movie":
            title_part = name_only[: year_match.start()]

    title = _beta_title_from_path(src_path, title_part, media_type)
    try:
        size_bytes = int(os.path.getsize(src_path))
    except Exception:
        size_bytes = 0

    hdr_reason = _hdr_filename_reason(src_path)
    return {
        "id": uuid.uuid5(uuid.NAMESPACE_URL, src_path).hex,
        "type": media_type,
        "title": title,
        "year": year,
        "season": season,
        "episode": episode,
        "filename": filename,
        "path": src_path,
        "folder": os.path.dirname(src_path),
        "size_bytes": size_bytes,
        "is_hdr": bool(hdr_reason),
        "hdr_reason": hdr_reason,
        "detected_reason": source_type.get("reason") or "filename",
        "target": _wizard_source_target("show" if media_type == "show" else "movie"),
    }


def _beta_clean_tmdb_secret(value: str) -> str:
    value = str(value or "").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def _beta_looks_like_tmdb_bearer(value: str) -> bool:
    value = _beta_clean_tmdb_secret(value)
    return value.startswith("eyJ") or value.count(".") >= 2


def _beta_tmdb_config(settings: dict):
    bearer = _beta_clean_tmdb_secret(settings.get("tmdb_bearer_token") or "")
    api_key = _beta_clean_tmdb_secret(settings.get("tmdb_api_key") or "")
    if not bearer and _beta_looks_like_tmdb_bearer(api_key):
        bearer = api_key
        api_key = ""
    if bearer:
        return {"Authorization": f"Bearer {bearer}"}, {}
    if api_key:
        return {}, {"api_key": api_key}
    return None


def _beta_tmdb_auth_cache_tag(settings: dict) -> str:
    auth = _beta_tmdb_config(settings or {})
    if not auth:
        return "off"
    headers, extra_params = auth
    secret = headers.get("Authorization") or extra_params.get("api_key") or ""
    if not secret:
        return "off"
    return hashlib.sha256(secret.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _beta_tmdb_search(media_type: str, title: str, year=None, settings=None) -> dict:
    settings = settings or {}
    auth = _beta_tmdb_config(settings)
    if not auth or not title:
        return {"configured": bool(auth), "poster_url": "", "source": "placeholder"}

    cache_key = (media_type, title.lower(), str(year or ""), _beta_tmdb_auth_cache_tag(settings))
    cached = BETA_POSTER_CACHE.get(cache_key)
    if cached:
        return cached.copy()

    headers, extra_params = auth
    endpoint = "tv" if media_type == "show" else "movie"
    params = {
        "query": title,
        "include_adult": "false",
        "language": "en-US",
        "page": "1",
        **extra_params,
    }
    if year:
        params["first_air_date_year" if media_type == "show" else "year"] = str(year)

    url = f"https://api.themoviedb.org/3/search/{endpoint}?{urlencode(params)}"
    req = Request(url, headers={"accept": "application/json", **headers})
    try:
        with urlopen(req, timeout=8) as res:
            payload = json.loads(res.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        result = {"configured": True, "poster_url": "", "source": "tmdb_error", "error": str(e)[:180]}
        BETA_POSTER_CACHE[cache_key] = result
        return result.copy()

    rows = payload.get("results") if isinstance(payload, dict) else []
    rows = rows if isinstance(rows, list) else []
    best = next((row for row in rows if row.get("poster_path")), rows[0] if rows else None)
    if not isinstance(best, dict):
        result = {"configured": True, "poster_url": "", "source": "tmdb_empty"}
        BETA_POSTER_CACHE[cache_key] = result
        return result.copy()

    poster_path = best.get("poster_path") or ""
    poster_url = f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else ""
    result = {
        "configured": True,
        "poster_url": poster_url,
        "source": "tmdb" if poster_url else "tmdb_no_poster",
        "tmdb_id": best.get("id"),
        "tmdb_title": best.get("name") or best.get("title") or "",
        "tmdb_year": (best.get("first_air_date") or best.get("release_date") or "")[:4],
    }
    BETA_POSTER_CACHE[cache_key] = result
    return result.copy()


def _beta_tmdb_season_art(tmdb_id, seasons: list[int], settings=None) -> dict:
    settings = settings or {}
    auth = _beta_tmdb_config(settings)
    if not auth or not tmdb_id:
        return {}

    headers, extra_params = auth
    auth_tag = _beta_tmdb_auth_cache_tag(settings)
    art = {}
    for raw_season in seasons or []:
        try:
            season = int(raw_season)
        except (TypeError, ValueError):
            continue
        if season < 0:
            continue

        cache_key = ("season", str(tmdb_id), str(season), auth_tag)
        cached = BETA_POSTER_CACHE.get(cache_key)
        if cached:
            result = cached.copy()
        else:
            params = {"language": "en-US", **extra_params}
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}?{urlencode(params)}"
            req = Request(url, headers={"accept": "application/json", **headers})
            try:
                with urlopen(req, timeout=8) as res:
                    payload = json.loads(res.read().decode("utf-8", errors="replace"))
                poster_path = payload.get("poster_path") if isinstance(payload, dict) else ""
                poster_url = f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else ""
                result = {"poster_url": poster_url, "source": "tmdb_season" if poster_url else "tmdb_season_no_poster"}
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                result = {"poster_url": "", "source": "tmdb_error", "error": str(e)[:180]}
            BETA_POSTER_CACHE[cache_key] = result

        if result.get("poster_url"):
            art[str(season)] = result["poster_url"]
    return art


def _beta_scan_library(root_path: str, *, recursive: bool, posters: bool, settings: dict, root_kind: str = "") -> dict:
    movies = []
    shows = {}
    scanned = 0
    skipped_tsd = 0

    walker = os.walk(root_path) if recursive else [(root_path, [], os.listdir(root_path))]
    for root_dir, _dirs, names in walker:
        for name in sorted(names):
            if not name.lower().endswith(VIDEO_EXTS):
                continue
            full = os.path.join(root_dir, name)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(name)[0].lower().endswith("-tsd"):
                skipped_tsd += 1
                continue

            item = _beta_parse_media(full)
            if root_kind == "movies":
                item["type"] = "movie"
                item["target"] = _wizard_source_target("movie")
            elif root_kind == "shows":
                item["type"] = "show"
                item["target"] = _wizard_source_target("show")
            scanned += 1
            if item["type"] == "show":
                key = f"{item['title'].lower()}::{item.get('year') or ''}"
                group = shows.setdefault(
                    key,
                    {
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, key).hex,
                        "type": "show",
                        "title": item["title"],
                        "year": item.get("year"),
                        "episode_count": 0,
                        "season_count": 0,
                        "seasons": [],
                        "total_size_bytes": 0,
                        "files": [],
                        "target": _wizard_source_target("show"),
                    },
                )
                group["episode_count"] += 1
                group["total_size_bytes"] += item["size_bytes"]
                group["files"].append(item)
            else:
                movies.append(item)

    for group in shows.values():
        seasons = sorted({ep["season"] for ep in group["files"] if ep.get("season") is not None})
        group["season_count"] = len(seasons)
        group["seasons"] = seasons
        group["files"].sort(key=lambda ep: (ep.get("season") or 0, ep.get("episode") or 0, ep["filename"].lower()))
        if posters:
            group.update(_beta_tmdb_search("show", group["title"], group.get("year"), settings))
            group["season_art"] = _beta_tmdb_season_art(group.get("tmdb_id"), seasons, settings)

    if posters:
        for item in movies:
            item.update(_beta_tmdb_search("movie", item["title"], item.get("year"), settings))

    movies.sort(key=lambda item: ((item.get("title") or "").lower(), item.get("year") or 0))
    show_rows = sorted(shows.values(), key=lambda item: ((item.get("title") or "").lower(), item.get("year") or 0))

    return {
        "scope": "root",
        "root": root_path,
        "roots": [next((row for row in _beta_mapped_roots(settings) if row["path"] == root_path), {"path": root_path, "label": root_path})],
        "recursive": recursive,
        "stats": {
            "movies": len(movies),
            "shows": len(show_rows),
            "episodes": sum(row["episode_count"] for row in show_rows),
            "scanned": scanned,
            "skipped_tsd": skipped_tsd,
            "limited": False,
        },
        "tmdb_configured": bool(_beta_tmdb_config(settings)),
        "movies": movies,
        "shows": show_rows,
    }


def _beta_merge_show_group(groups: dict, incoming: dict) -> None:
    key = f"{str(incoming.get('title') or '').lower()}::{incoming.get('year') or ''}"
    group = groups.setdefault(
        key,
        {
            "id": incoming.get("id") or uuid.uuid5(uuid.NAMESPACE_DNS, key).hex,
            "type": "show",
            "title": incoming.get("title") or "Unknown Title",
            "year": incoming.get("year"),
            "episode_count": 0,
            "season_count": 0,
            "seasons": [],
            "total_size_bytes": 0,
            "files": [],
            "target": incoming.get("target") or _wizard_source_target("show"),
        },
    )

    group["episode_count"] += int(incoming.get("episode_count") or 0)
    group["total_size_bytes"] += int(incoming.get("total_size_bytes") or 0)
    group["files"].extend(incoming.get("files") or [])

    for key_name in ("poster_url", "source", "tmdb_id", "tmdb_title", "tmdb_year", "error"):
        if not group.get(key_name) and incoming.get(key_name):
            group[key_name] = incoming.get(key_name)

    incoming_art = incoming.get("season_art") if isinstance(incoming.get("season_art"), dict) else {}
    if incoming_art:
        group_art = group.setdefault("season_art", {})
        if isinstance(group_art, dict):
            for season, poster_url in incoming_art.items():
                if poster_url and not group_art.get(str(season)):
                    group_art[str(season)] = poster_url

    seasons = sorted({ep["season"] for ep in group["files"] if ep.get("season") is not None})
    group["season_count"] = len(seasons)
    group["seasons"] = seasons
    group["files"].sort(key=lambda ep: (ep.get("season") or 0, ep.get("episode") or 0, ep.get("filename", "").lower()))


def _beta_combine_library_scans(scans: list[dict], *, recursive: bool, settings: dict) -> dict:
    movies = []
    show_groups = {}
    roots = []
    skipped_tsd = 0
    scanned = 0

    for scan in scans:
        if not isinstance(scan, dict):
            continue
        roots.extend(scan.get("roots") or [])
        movies.extend(scan.get("movies") or [])
        for show in scan.get("shows") or []:
            _beta_merge_show_group(show_groups, show)
        stats = scan.get("stats") or {}
        skipped_tsd += int(stats.get("skipped_tsd") or 0)
        scanned += int(stats.get("scanned") or 0)

    movies.sort(key=lambda item: ((item.get("title") or "").lower(), item.get("year") or 0))
    show_rows = sorted(show_groups.values(), key=lambda item: ((item.get("title") or "").lower(), item.get("year") or 0))

    return {
        "scope": "all",
        "root": "__all__",
        "roots": roots,
        "recursive": recursive,
        "stats": {
            "movies": len(movies),
            "shows": len(show_rows),
            "episodes": sum(int(row.get("episode_count") or 0) for row in show_rows),
            "scanned": scanned,
            "skipped_tsd": skipped_tsd,
            "limited": False,
        },
        "tmdb_configured": bool(_beta_tmdb_config(settings)),
        "movies": movies,
        "shows": show_rows,
    }


def _beta_refresh_predictions(data: dict) -> dict:
    data = data if isinstance(data, dict) else {}
    model = _history_prediction_model()

    for item in data.get("movies") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        preset = guess_preset_from_filename(os.path.basename(path))
        filename_hdr_reason = _hdr_filename_reason(path)
        is_hdr = bool(item.get("is_hdr") or filename_hdr_reason)
        item["is_hdr"] = is_hdr
        if is_hdr and (not item.get("hdr_reason") or item.get("hdr_reason") == "filename"):
            item["hdr_reason"] = filename_hdr_reason or item.get("hdr_reason") or "filename"
        item["prediction"] = _history_prediction_for(int(item.get("size_bytes") or 0), preset, is_hdr, model)

    for show in data.get("shows") or []:
        if not isinstance(show, dict):
            continue
        file_predictions = []
        show_is_hdr = bool(show.get("is_hdr"))
        for ep in show.get("files") or []:
            if not isinstance(ep, dict):
                continue
            path = str(ep.get("path") or "")
            preset = guess_preset_from_filename(os.path.basename(path))
            filename_hdr_reason = _hdr_filename_reason(path)
            is_hdr = bool(ep.get("is_hdr") or filename_hdr_reason)
            ep["is_hdr"] = is_hdr
            if is_hdr and (not ep.get("hdr_reason") or ep.get("hdr_reason") == "filename"):
                ep["hdr_reason"] = filename_hdr_reason or ep.get("hdr_reason") or "filename"
            show_is_hdr = show_is_hdr or is_hdr
            ep["prediction"] = _history_prediction_for(int(ep.get("size_bytes") or 0), preset, is_hdr, model)
            file_predictions.append(ep["prediction"])
        show["is_hdr"] = bool(show_is_hdr)
        if show["is_hdr"] and not show.get("hdr_reason"):
            show["hdr_reason"] = "episode"
        show["prediction"] = _combine_history_predictions(file_predictions, int(show.get("total_size_bytes") or 0))

    return data


def _beta_scan_all_libraries(*, recursive: bool, posters: bool, settings: dict) -> dict:
    scans = []
    for row in _beta_mapped_roots(settings):
        root_path = row["path"]
        if not root_path or not is_allowed_path(root_path) or not os.path.isdir(root_path):
            continue
        scan = _beta_scan_library(
            root_path,
            recursive=recursive,
            posters=posters,
            settings=settings,
            root_kind=row.get("kind") or "",
        )
        scans.append(scan)

    return _beta_combine_library_scans(scans, recursive=recursive, settings=settings)


def _beta_stamp_library_scan(data: dict) -> dict:
    data = data if isinstance(data, dict) else {}
    data["generated_at"] = time.time()
    return data


# -------------------------------------------------------------------
# Side-by-side preview helpers
# -------------------------------------------------------------------

def _b64_jpg(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _ffmpeg_extract_jpg(input_path: str, t_sec: float, out_path: str) -> None:
    # -ss before -i is fast seek (good enough for preview)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-ss", str(max(0.0, float(t_sec))),
        "-i", input_path,
        "-frames:v", "1",
        "-q:v", "2",
        out_path,
    ]
    ok, out, err = _run_cmd(cmd)
    if not ok or not os.path.isfile(out_path):
        raise RuntimeError(f"ffmpeg frame extract failed: {(err or out or '').strip()[:400]}")

def _collect_preset_names(obj):
    """Recursively collect all PresetName strings from a HandBrake preset JSON structure."""
    names = []

    if isinstance(obj, dict):
        # direct hit
        if isinstance(obj.get("PresetName"), str) and obj["PresetName"].strip():
            names.append(obj["PresetName"].strip())

        # common structures
        for k, v in obj.items():
            names.extend(_collect_preset_names(v))

    elif isinstance(obj, list):
        for item in obj:
            names.extend(_collect_preset_names(item))

    return names


def _preset_names_from_file(preset_file: str):
    """Load preset JSON and return a de-duped list of PresetName values in order."""
    with open(preset_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw = _collect_preset_names(data)

    # de-dupe while preserving order
    seen = set()
    out = []
    for n in raw:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _pick_best_preset_name(names, base_hint: str):
    """
    If there are multiple presets in one file, pick a reasonable one.
    - If base_hint includes '4k', prefer names containing '4k' or '2160'
    - If base_hint includes '1080', prefer names containing '1080'
    Otherwise pick the first.
    """
    if not names:
        return None

    hint = (base_hint or "").lower()

    if "4k" in hint:
        for n in names:
            nl = n.lower()
            if "4k" in nl or "2160" in nl:
                return n

    if "1080" in hint:
        for n in names:
            nl = n.lower()
            if "1080" in nl:
                return n

    return names[0]



def _hb_preset_args_for_base(base: str, src_basename: str):
    """
    Convert preset base selection (1080/4k/auto) into HandBrakeCLI preset args.
    Uses preset_config mapping, but if the configured preset name is wrong,
    auto-picks the correct PresetName from the preset JSON and saves it.
    """
    base = (base or "auto").lower()
    effective = base
    if effective == "auto":
        effective = guess_preset_from_filename(src_basename)

    cfg = preset_config.get(effective)
    if not cfg:
        raise RuntimeError(f"Unknown preset base: {effective}")

    preset_file = cfg.get("file")
    preset_name = cfg.get("name")

    if not preset_file or not os.path.isfile(preset_file):
        raise RuntimeError(f"Preset file missing: {preset_file}")

    # Auto-pick preset name from the JSON if missing or incorrect
    try:
        names = _preset_names_from_file(preset_file)
        if not names:
            raise RuntimeError("No PresetName found inside preset JSON")

        # If current name is not in the JSON, pick a valid one and persist it
        if (not preset_name) or (preset_name not in names):
            picked = _pick_best_preset_name(names, effective) or names[0]
            preset_config[effective]["name"] = picked
            save_preset_config()
            preset_name = picked

    except Exception as e:
        # If JSON parsing fails, keep old behavior but with a clearer error
        if not preset_name:
            raise RuntimeError(f"Preset name missing and could not auto-detect from JSON: {e}")

    # HandBrakeCLI preset usage:
    # --preset-import-file <file>  and  -Z "<preset name>"
    return effective, ["--preset-import-file", preset_file, "-Z", preset_name]

def _preset_names_in_file(preset_file: str):
    try:
        with open(preset_file, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception:
        return []

    names = []

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("PresetName"), str):
                names.append(x["PresetName"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(j)

    # de-dupe preserve order
    out, seen = [], set()
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _flatten_args(arg_list):
    """
    Turn a list that may contain combined strings into a clean argv list.
    e.g. ["--width 1920 --height 1080", "--encoder-preset", "slow"]
      -> ["--width","1920","--height","1080","--encoder-preset","slow"]
    """
    out = []
    for a in (arg_list or []):
        if a is None:
            continue
        if isinstance(a, (list, tuple)):
            out.extend([str(x) for x in a if x is not None])
        else:
            out.extend(str(a).split())
    return out


# -------------------------------------------------------------------
# Route registration
# -------------------------------------------------------------------

def register_routes(app):
    """Attach all routes to the given Flask app."""

    # -------------- cancel preview -----------

    @app.route("/wizard_preview_cancel", methods=["POST"])
    def wizard_preview_cancel():
        data = request.get_json(silent=True) or {}
        preview_id = (data.get("preview_id") or "").strip()
        killed = _kill_preview_by_id(preview_id)
        return jsonify(ok=True, killed=killed)



    # ------------- UI -------------

    @app.route("/")
    def index():
        """Render the main single-page web UI."""
        preset_files = list_preset_files()
        settings = load_settings()
        return render_template(
            "index.html",
            roots=ROOTS,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
            settings=settings,
        )

    @app.route("/size_wizard")
    def size_wizard_page():
        """Render the Size Wizard page (prefill via query string)."""
        return render_template("size_wizard.html")

    @app.route("/beta")
    def beta_page():
        """Render the experimental media organizer page."""
        settings = load_settings()
        return render_template(
            "beta.html",
            roots=_beta_roots_payload(settings),
            tmdb_configured=bool(_beta_tmdb_config(settings)),
        )

    @app.route("/api/beta/library")
    def beta_library_api():
        """Scan an allowed media root and group videos into movies and shows."""
        root = request.args.get("root") or "__all__"
        if not root:
            return jsonify(error="no media roots configured"), 400
        settings = load_settings()
        if root != "__all__":
            if not _beta_root_is_mapped(root, settings):
                return jsonify(error="root is not mapped for Beta scanning"), 400
            if not is_allowed_path(root) or not os.path.isdir(root):
                return jsonify(error="root path not allowed or not a directory"), 400

        recursive = str(request.args.get("recursive", "1")).lower() not in {"0", "false", "no"}
        posters = str(request.args.get("posters", "1")).lower() not in {"0", "false", "no"}

        try:
            if root == "__all__":
                data = _beta_scan_all_libraries(
                    recursive=recursive,
                    posters=posters,
                    settings=settings,
                )
            else:
                mapped_root = next((row for row in _beta_mapped_roots(settings) if row["path"] == root), {})
                data = _beta_scan_library(
                    root,
                    recursive=recursive,
                    posters=posters,
                    settings=settings,
                    root_kind=mapped_root.get("kind") or "",
                )
            data = _beta_refresh_predictions(data)
            tracking = _beta_load_tracking()
            data = _beta_apply_tracking(data, tracking)
            auto_queue = _beta_auto_queue_tracked_episodes(data, tracking)
            _beta_save_tracking(tracking)
            data = _beta_apply_tracking(data, tracking)
            data.setdefault("tracking", {})["auto_queue"] = auto_queue
            data = _beta_stamp_library_scan(data)
            _beta_save_library_cache(data)
        except Exception as e:
            return jsonify(error=str(e)), 500

        return jsonify(data)

    @app.route("/api/beta/library_cache")
    def beta_library_cache_api():
        """Return the last saved Beta library scan without touching the filesystem tree."""
        return jsonify(_beta_load_library_cache(load_settings()))

    @app.route("/api/beta/tracked_show", methods=["POST"])
    def beta_tracked_show_api():
        """Enable or disable auto-queue tracking for a Beta show group."""
        data = request.get_json(force=True) or {}
        tracked = bool(data.get("tracked"))
        show_id = str(data.get("show_id") or data.get("id") or "").strip()
        if not show_id:
            show_id = _beta_show_tracking_key(data)
        title = str(data.get("title") or "Unknown Title").strip() or "Unknown Title"
        paths = _beta_clean_path_list(data.get("paths"))

        tracking = _beta_load_tracking()
        shows = tracking.setdefault("shows", {})
        now = time.time()
        if tracked:
            existing = shows.get(show_id) if isinstance(shows.get(show_id), dict) else {}
            shows[show_id] = {
                "id": show_id,
                "title": title,
                "year": data.get("year"),
                "tmdb_id": data.get("tmdb_id"),
                "poster_url": str(data.get("poster_url") or ""),
                "tracked": True,
                "known_paths": paths,
                "created_at": float(existing.get("created_at") or now),
                "updated_at": now,
            }
        else:
            shows.pop(show_id, None)

        _beta_save_tracking(tracking)
        return jsonify(
            ok=True,
            show_id=show_id,
            tracked=tracked,
            tracked_count=sum(1 for row in shows.values() if isinstance(row, dict) and row.get("tracked")),
        )

    @app.route("/api/beta/queue", methods=["POST"])
    def beta_queue_api():
        """Queue selected Beta library files using the normal Jobs presets."""
        data = request.get_json(force=True) or {}
        preset = str(data.get("preset") or "auto").strip().lower()
        if preset not in {"auto", "1080", "4k"}:
            return jsonify(error="invalid preset"), 400

        raw_paths = data.get("paths")
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        if not isinstance(raw_paths, list):
            return jsonify(error="missing paths"), 400

        seen = set()
        to_create = []
        skipped = []
        for raw in raw_paths:
            src = str(raw or "").strip()
            if not src or src in seen:
                continue
            seen.add(src)

            reason = ""
            if not os.path.isfile(src):
                reason = "not a file"
            elif not is_allowed_path(src):
                reason = "path not allowed"
            elif not src.lower().endswith(VIDEO_EXTS):
                reason = "not a video"
            elif os.path.splitext(os.path.basename(src))[0].lower().endswith("-tsd"):
                reason = "already tagged -TSD"

            if reason:
                skipped.append({"path": src, "reason": reason})
                continue

            effective_preset = guess_preset_from_filename(os.path.basename(src)) if preset == "auto" else preset
            to_create.append((src, effective_preset))

        if not to_create:
            return jsonify(error="no queueable files selected", skipped=skipped), 400

        count = create_jobs_batch(to_create)
        return jsonify(
            ok=True,
            count=count,
            requested=len(seen),
            skipped=skipped,
            preset=preset,
        )

    @app.route("/api/wizard_presets", methods=["GET", "POST"])
    def wizard_presets_api():
        """List or save Size Wizard recipes."""
        if request.method == "GET":
            return jsonify(presets=_load_wizard_presets())

        data = request.get_json(force=True) or {}
        try:
            preset_id = str(data.get("id") or "").strip()
            name = _clean_wizard_preset_name(data.get("name") or "")
            options_data = data.get("options") if isinstance(data.get("options"), dict) else data
            options = _wizard_public_options(options_data)
        except ValueError as e:
            return jsonify(error=str(e)), 400

        rows = _load_wizard_presets()
        now = time.time()
        existing = None
        for row in rows:
            if preset_id and row.get("id") == preset_id:
                existing = row
                break
            if not preset_id and row.get("name", "").strip().lower() == name.lower():
                existing = row
                break

        if existing:
            existing["name"] = name
            existing["options"] = options
            existing["updated_at"] = now
            saved = existing
        else:
            saved = {
                "id": uuid.uuid4().hex,
                "name": name,
                "options": options,
                "created_at": now,
                "updated_at": now,
            }
            rows.append(saved)

        rows.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
        _save_wizard_presets(rows)
        return jsonify(ok=True, preset=saved, presets=_load_wizard_presets())

    @app.route("/api/wizard_presets/<preset_id>", methods=["DELETE"])
    def wizard_preset_delete_api(preset_id):
        """Delete a saved Size Wizard recipe."""
        preset_id = (preset_id or "").strip()
        rows = _load_wizard_presets()
        kept = [row for row in rows if row.get("id") != preset_id]
        if len(kept) == len(rows):
            return jsonify(error="wizard preset not found"), 404
        _save_wizard_presets(kept)
        return jsonify(ok=True, presets=_load_wizard_presets())

    @app.route("/settings")
    def settings_page():
        """Render the settings page (global app settings)."""
        settings = load_settings()
        preset_files = list_preset_files()
        return render_template(
            "settings.html",
            settings=settings,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
            roots=_beta_roots_payload(settings),
            allowed_roots=[{"path": path, "label": label or path} for path, label in ROOTS],
        )

    @app.route("/debug_config")
    def debug_config():
        """Debug endpoint showing roots and preset files."""
        preset_files = list_preset_files()
        return jsonify(
            roots=ROOTS,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
        )

    # ------------- Global settings (JSON API) -------------

    @app.route("/api/settings", methods=["GET", "POST"])
    def settings_api():
        """GET returns settings; POST updates settings."""
        if request.method == "GET":
            settings = load_settings()
            return jsonify(settings=settings)

        data = request.get_json(silent=True) or {}
        old_tmdb_tag = _beta_tmdb_auth_cache_tag(load_settings())
        new_settings = save_settings(data)
        tmdb_changed = _beta_tmdb_auth_cache_tag(new_settings) != old_tmdb_tag
        if tmdb_changed:
            BETA_POSTER_CACHE.clear()
            _beta_clear_library_cache()
        return jsonify(settings=new_settings, tmdb_changed=tmdb_changed)

    # ------------- CPU profiles (JSON API) -------------

    @app.route("/api/cpu_profiles", methods=["GET"])
    def cpu_profiles_api():
        """Return CPU profiles for the Settings dropdown / ETA estimation."""
        return jsonify(profiles=list_cpu_profiles())

    # ------------- Events (Lidarr-style feed) -------------

    @app.route("/api/events", methods=["GET"])
    def events_api():
        """Return newest-first event log entries."""
        try:
            limit = int(request.args.get("limit") or 200)
        except ValueError:
            limit = 200
        limit = max(1, min(2000, limit))
        return jsonify(events=load_events(limit=limit))

    @app.route("/api/events/clear", methods=["POST"])
    def events_clear_api():
        clear_events()
        return jsonify(ok=True)

    # ------------- Storage savings stats -------------

    @app.route("/api/storage_stats/summary", methods=["GET"])
    def storage_summary_api():
        return jsonify(summary=get_storage_summary())

    @app.route("/api/storage_stats", methods=["GET"])
    def storage_list_api():
        try:
            limit = int(request.args.get("limit") or 200)
        except ValueError:
            limit = 200
        limit = max(1, min(5000, limit))
        return jsonify(encodes=list_storage_encodes(limit=limit))

    @app.route("/api/storage_stats/clear", methods=["POST"])
    def storage_clear_api():
        clear_storage_stats()
        return jsonify(ok=True)


    # ------------- Directory listing -------------

    @app.route("/list")
    def list_path():
        """List folders + video files for a given path (used by the browser UI)."""
        path = request.args.get("path")
        if not path:
            return jsonify(error="missing path"), 400

        if not is_allowed_path(path) or not os.path.isdir(path):
            return jsonify(error="path not allowed or not a directory"), 400

        try:
            entries = os.listdir(path)
        except Exception as e:
            return jsonify(error=str(e)), 500

        dirs = sorted([e for e in entries if os.path.isdir(os.path.join(path, e))])
        files = sorted(
            [
                e
                for e in entries
                if os.path.isfile(os.path.join(path, e))
                and e.lower().endswith(VIDEO_EXTS)
            ]
        )
        file_details = {}
        for name in files:
            full = os.path.join(path, name)
            try:
                stat = os.stat(full)
                file_details[name] = {
                    "size_bytes": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                    "codec_hint": (
                        "AV1" if re.search(r"\bav1\b", name, re.IGNORECASE)
                        else "HEVC" if re.search(r"\b(?:hevc|h[ ._-]*265|x265)\b", name, re.IGNORECASE)
                        else "H.264" if re.search(r"\b(?:h[ ._-]*264|x264)\b", name, re.IGNORECASE)
                        else ""
                    ),
                }
            except Exception:
                file_details[name] = {"size_bytes": 0, "mtime": 0, "codec_hint": ""}

        return jsonify(path=path, dirs=dirs, files=files, file_details=file_details)

    # ------------- Single encode -------------

    @app.route("/encode", methods=["POST"])
    def encode():
        """Queue a single file for encoding."""
        data = request.get_json(force=True)
        src = data.get("src")
        preset = data.get("preset") or "1080"

        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400

        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        base = os.path.basename(src)
        name_only, _ext = os.path.splitext(base)
        if name_only.lower().endswith("-tsd"):
            return jsonify(error="file already tagged -TSD, not queuing"), 400

        if preset == "auto":
            preset = guess_preset_from_filename(base)

        job_id = create_job(src, preset)
        return jsonify(job_id=job_id)

    @app.route("/encode_wizard", methods=["POST"])
    def encode_wizard():
        """Queue an encode with Size Wizard options."""
        data = request.get_json(force=True)

        try:
            plan = _wizard_plan(data, probe_func=_probe_media, for_queue=True, preview=False)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:
            return jsonify(error=str(e)), 500

        job_id = create_job(plan["src"], plan["preset"], extra_args=" ".join(plan["extra_args"]))
        return jsonify(
            job_id=job_id,
            preset=plan["preset"],
            extra_args=plan["extra_args"],
            estimates=plan["estimates"],
        )

    # ------------- Wizard preview helpers -------------

    @app.route("/probe")
    def probe():
        """Probe a media file to get basic info (duration/resolution/fps)."""
        src = request.args.get("src")
        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400
        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400
        try:
            info = _probe_media(src)
            return jsonify(src=src, info=info)
        except Exception as e:
            return jsonify(error=str(e)), 500


    
    def _ffmpeg_extract_jpg_scaled(src_path: str, t_sec: int, out_jpg: str, w: int, h: int):
        """Extract a single JPEG frame at integer second t_sec, optionally scaled."""
        # Use integer seconds to avoid keyframe seek surprises.
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", str(int(t_sec)),
            "-i", src_path,
            "-frames:v", "1",
            "-vf", f"scale={int(w)}:{int(h)}:flags=bicubic",
            "-q:v", "2",
            "-y", out_jpg,
        ]
        ok, out, err = _run_cmd(cmd)
        if not ok or not os.path.isfile(out_jpg):
            raise RuntimeError((err or out or "ffmpeg failed").strip())


    def _remove_preview_clip(path: str):
        try:
            os.remove(path)
        except Exception:
            pass
        try:
            parent = os.path.dirname(path)
            if os.path.basename(parent).startswith("hbwiz_"):
                os.rmdir(parent)
        except Exception:
            pass


    def _register_preview_clip(token: str, path: str):
        # Keep a small in-memory registry so we can serve clips by token.
        # Clips are cleaned up lazily on new preview requests.
        now = time.time()
        PREVIEW_CLIPS[token] = (path, now)

        # Lazy cleanup (keep up to 30 clips or 30 minutes)
        try:
            if len(PREVIEW_CLIPS) > 30:
                # Remove oldest
                for tok, (p, ts) in sorted(PREVIEW_CLIPS.items(), key=lambda kv: kv[1][1])[:-30]:
                    PREVIEW_CLIPS.pop(tok, None)
                    _remove_preview_clip(p)
            cutoff = now - (30 * 60)
            for tok, (p, ts) in list(PREVIEW_CLIPS.items()):
                if ts < cutoff:
                    PREVIEW_CLIPS.pop(tok, None)
                    _remove_preview_clip(p)
        except Exception:
            pass


    @app.route("/wizard_preview_clip/<token>", methods=["GET"])
    def wizard_preview_clip(token):
        """Serve a previously generated preview MP4 clip."""
        item = PREVIEW_CLIPS.get(token)
        if not item:
            abort(404)
        path, _ts = item
        if not os.path.isfile(path):
            abort(404)
        return send_file(path, mimetype="video/mp4", as_attachment=False)


    @app.route("/wizard_preview_fast_images", methods=["POST"])
    def wizard_preview_fast_images():
        """Fast visual compare: OLD frame vs NEW (scaled) frame. No HandBrake."""
        data = request.get_json(force=True) or {}
        src = data.get("src")
        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400
        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400

        # Make sure ffmpeg exists
        ok_ff, _o, _e = _run_cmd(["ffmpeg", "-version"])
        if not ok_ff:
            return jsonify(error="ffmpeg not found in container (needed for previews)"), 500

        try:
            plan = _wizard_plan(data, probe_func=_ffprobe_media_fast, preview=True)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:
            return jsonify(error=str(e)), 500

        info = plan["probe"]
        duration_sec = float(info.get("duration_sec") or 0.0)

        # Preview timestamp (integer seconds)
        if duration_sec < 120:
            t = max(2.0, min(duration_sec * 0.10, duration_sec - 2.0))
        else:
            t = min(60.0, duration_sec - 2.0)
        t_int = int(max(0.0, t))

        out_res = plan["estimates"]["output_resolution"]
        out_w = int(out_res.get("width") or 0)
        out_h = int(out_res.get("height") or 0)
        decision = plan["estimates"].get("decision") or "keep"

        # Temp outputs
        tmpdir = tempfile.mkdtemp(prefix="hbwiz_fast_")
        token = uuid.uuid4().hex
        old_jpg = os.path.join(tmpdir, f"old_{token}.jpg")
        new_jpg = os.path.join(tmpdir, f"new_{token}.jpg")

        try:
            _ffmpeg_extract_jpg(src, t_int, old_jpg)
            _ffmpeg_extract_jpg_scaled(src, t_int, new_jpg, out_w, out_h)
            return jsonify(
                ok=True,
                mode="fast",
                t_seconds=float(t_int),
                decision=decision,
                out_w=out_w,
                out_h=out_h,
                old_b64=_b64_jpg(old_jpg),
                new_b64=_b64_jpg(new_jpg),
            )
        finally:
            # Best-effort cleanup
            try:
                os.remove(old_jpg)
                os.remove(new_jpg)
                os.rmdir(tmpdir)
            except Exception:
                pass



    @app.route("/wizard_preview_accurate", methods=["POST"])
    def wizard_preview_accurate():
        """
        Accurate preview: short HandBrake encode using the same wizard plan as queueing.
        """
        data = request.get_json(force=True) or {}

        try:
            plan = _wizard_plan(data, probe_func=_ffprobe_media_fast, preview=True)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:
            return jsonify(error=str(e)), 500

        src = plan["src"]
        base = os.path.basename(src)
        info = plan["probe"]
        duration_sec = float(info.get("duration_sec") or 0.0)
        estimates = plan["estimates"]
        out_res = estimates["output_resolution"]
        out_w = int(out_res.get("width") or 0)
        out_h = int(out_res.get("height") or 0)
        decision = estimates.get("decision") or "keep"
        video_kbps = float(estimates.get("video_bitrate_kbps") or 0)
        encoder_preset = estimates.get("encoder_preset") or ""
        encoder_label = estimates.get("encoder_label") or estimates.get("encoder") or ""

        # Preview timestamp (integer seconds)
        if duration_sec < 120:
            t = max(2.0, min(duration_sec * 0.10, duration_sec - 2.0))
        else:
            t = min(60.0, duration_sec - 2.0)
        t_int = int(max(0.0, t))

        # Temp files
        tmpdir = tempfile.mkdtemp(prefix="hbwiz_acc_")
        preview_id = (data.get("preview_id") or uuid.uuid4().hex).strip() or uuid.uuid4().hex
        token = uuid.uuid4().hex
        out_clip = os.path.join(tmpdir, f"clip_{token}.mp4")
        old_jpg = os.path.join(tmpdir, f"old_{token}.jpg")
        new_jpg = os.path.join(tmpdir, f"new_{token}.jpg")

        # Extract OLD frame at t_int
        try:
            _ffmpeg_extract_jpg(src, t_int, old_jpg)
        except Exception as e:
            return jsonify(error=f"failed extracting source frame: {e}"), 500

        # HandBrake short-segment preview (accurate)
        preview_seconds = int(max(6, min(10, duration_sec - t_int - 1)))

        try:
            _effective, preset_a = _hb_preset_args_for_base(plan["preset"], base)
        except Exception as e:
            return jsonify(error=str(e)), 500

        hb_cmd = [
            "HandBrakeCLI",
            "-i", src,
            "-o", out_clip,
            "--start-at", f"duration:{t_int}",
            "--stop-at", f"duration:{preview_seconds}",
        ] + preset_a

        hb_cmd += _flatten_args(plan["extra_args"])
        hb_cmd += ["-a", "none"]

        # Kill any previous preview for this preview_id before starting a new one
        _kill_preview_by_id(preview_id)

        pidfile = _preview_pidfile(preview_id)

        p = subprocess.Popen(
            hb_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        try:
            with open(pidfile, "w", encoding="utf-8") as f:
                f.write(str(p.pid))
        except Exception:
            pass

        try:
            out, err = p.communicate(timeout=180)
            ok = (p.returncode == 0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                time.sleep(0.25)
                os.killpg(p.pid, signal.SIGKILL)
            except Exception:
                pass
            ok, out, err = False, "", "HandBrake preview timed out"
        finally:
            try:
                os.remove(pidfile)
            except Exception:
                pass

        if not ok or (not os.path.isfile(out_clip)):
            snippet = ((err or "") + "\n" + (out or "")).strip().replace("\r", "\n")
            snippet = snippet[:900]
            return jsonify(error=f"HandBrake accurate preview failed: {snippet}"), 500

        # Extract NEW frame from the preview clip (same timestamp within the segment)
        try:
            # Since clip starts at t_int, sample ~2s into the clip (or mid if very short)
            within = 2.0 if preview_seconds >= 4 else max(0.5, preview_seconds * 0.5)
            _ffmpeg_extract_jpg(out_clip, within, new_jpg)
        except Exception as e:
            return jsonify(error=f"failed extracting preview frame: {e}"), 500

        _register_preview_clip(token, out_clip)

        try:
            return jsonify(
                ok=True,
                preview_id=preview_id,
                t_seconds=t_int,
                seconds=preview_seconds,
                preview_seconds=preview_seconds,
                preset=plan["preset"],
                decision=decision,
                out_width=out_w,
                out_height=out_h,
                bitrate_kbps=int(video_kbps),
                encoder=estimates.get("encoder"),
                encoder_label=encoder_label,
                encoder_preset=encoder_preset,
                clip_url=f"/wizard_preview_clip/{token}",
                old_b64=_b64_jpg(old_jpg),
                new_b64=_b64_jpg(new_jpg),
            )
        finally:
            try:
                os.remove(old_jpg)
                os.remove(new_jpg)
                os.rmdir(tmpdir)
            except Exception:
                pass
    @app.route("/wizard_preview_images", methods=["POST"])
    def wizard_preview_images():
        return wizard_preview_accurate()



    @app.route("/wizard_preview", methods=["POST"])
    def wizard_preview():
        """Return an estimated outcome for Size Wizard inputs."""
        data = request.get_json(force=True) or {}
        try:
            plan = _wizard_plan(data, probe_func=_probe_media, preview=False)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        except Exception as e:
            return jsonify(error=str(e)), 500

        return jsonify(
            src=plan["src"],
            preset=plan["preset"],
            probe=plan["probe"],
            inputs=plan["inputs"],
            estimates=plan["estimates"],
            suggested_extra_args=plan["extra_args"],
        )


    # ------------- Job status -------------

    @app.route("/status/<job_id>")
    def status(job_id):
        """Return status + recent log for a specific job."""
        job = get_job(job_id)
        if not job:
            return jsonify(error="job not found"), 404
        return jsonify(job)

    # ------------- Cancel job -------------

    @app.route("/cancel/<job_id>", methods=["POST"])
    def cancel_route(job_id):
        """Cancel a running job or mark a queued one as canceled."""
        ok, err = cancel_job(job_id)
        if not ok:
            return jsonify(error=err or "cancel failed"), 400
        return jsonify(ok=True, job_id=job_id)

    # ------------- Job list -------------

    @app.route("/jobs")
    def jobs_list():
        """Return a simplified list of all jobs for the history table."""
        items = list_jobs_for_api()
        return jsonify(jobs=items)

    @app.route("/jobs/summary")
    def jobs_summary():
        """Return dashboard metrics for the jobs page."""
        return jsonify(summary=get_job_summary())

    # ------------- Job log download -------------

    @app.route("/job_log/<job_id>")
    def job_log(job_id):
        """Download the full log file for a given job."""
        if not get_job(job_id):
            abort(404)
        log_path = os.path.join(LOG_DIR, f"{job_id}.log")
        if not os.path.isfile(log_path):
            abort(404)
        return send_file(
            log_path,
            mimetype="text/plain",
            as_attachment=True,
            download_name=f"{job_id}.log",
        )

    # ------------- Batch rename -------------

    @app.route("/batch_rename", methods=["POST"])
    def batch_rename():
        """Rename all video files in a directory to add -TSD before the extension."""
        data = request.get_json(force=True)
        path = data.get("path")

        if not path or not os.path.isdir(path):
            return jsonify(error="invalid path"), 400

        if not is_allowed_path(path):
            return jsonify(error="path not allowed"), 400

        renamed = 0
        skipped = 0

        try:
            for entry in os.listdir(path):
                full = os.path.join(path, entry)
                if not os.path.isfile(full):
                    continue

                if not entry.lower().endswith(VIDEO_EXTS):
                    continue

                name, ext = os.path.splitext(entry)
                if name.lower().endswith("-tsd"):
                    skipped += 1
                    continue

                new_name = f"{name}-TSD{ext}"
                new_full = os.path.join(path, new_name)

                if os.path.exists(new_full):
                    skipped += 1
                    continue

                os.rename(full, new_full)
                renamed += 1
        except Exception as e:
            return jsonify(error=str(e)), 500

        return jsonify(renamed_count=renamed, skipped_count=skipped)

    # ------------- Batch encode (non-recursive) -------------

    @app.route("/batch_encode", methods=["POST"])
    def batch_encode():
        """Queue encode jobs for all video files in a folder (non-recursive)."""
        data = request.get_json(force=True)
        path = data.get("path")
        preset = data.get("preset") or "1080"

        if not path or not os.path.isdir(path):
            return jsonify(error="invalid path"), 400

        if not is_allowed_path(path):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        files = sorted(
            [
                e
                for e in os.listdir(path)
                if os.path.isfile(os.path.join(path, e))
                and e.lower().endswith(VIDEO_EXTS)
                and not os.path.splitext(e)[0].lower().endswith("-tsd")
            ]
        )

        if not files:
            return jsonify(error="no video files found"), 400

        to_create = []
        for entry in files:
            src = os.path.join(path, entry)
            effective_preset = guess_preset_from_filename(entry) if preset == "auto" else preset
            to_create.append((src, effective_preset))

        count = create_jobs_batch(to_create)
        return jsonify(count=count)

    # ------------- Batch encode (recursive) -------------

    @app.route("/batch_encode_recursive", methods=["POST"])
    def batch_encode_recursive():
        """Queue encode jobs for all video files in a folder and all subfolders."""
        data = request.get_json(force=True)
        path = data.get("path")
        preset = data.get("preset") or "1080"

        if not path or not os.path.isdir(path):
            return jsonify(error="invalid path"), 400

        if not is_allowed_path(path):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        to_create = []
        for root, _dirs, files in os.walk(path):
            for entry in files:
                if not entry.lower().endswith(VIDEO_EXTS):
                    continue

                name, _ext = os.path.splitext(entry)
                if name.lower().endswith("-tsd"):
                    continue

                src = os.path.join(root, entry)
                effective_preset = guess_preset_from_filename(entry) if preset == "auto" else preset
                to_create.append((src, effective_preset))

        if not to_create:
            return jsonify(error="no video files found"), 400

        count = create_jobs_batch(to_create)
        return jsonify(count=count)

    # ------------- Clear finished jobs -------------

    @app.route("/clear_finished_jobs", methods=["POST"])
    def clear_finished_jobs_route():
        """Delete all finished jobs (done/error) from history and remove their logs."""
        removed = clear_finished_jobs_core()
        return jsonify(removed=removed)

    # ------------- Clear queued jobs -------------

    @app.route("/clear_queued_jobs", methods=["POST"])
    def clear_queued_jobs_route():
        """Delete all jobs that are currently queued (status == 'queued')."""
        removed = clear_queued_jobs()
        return jsonify(removed=removed)

    # ------------- Preset config (1080 / 4k mapping) -------------

    @app.route("/preset_config", methods=["GET", "POST"])
    def preset_config_route():
        """Get or update default preset files for 1080 and 4K."""
        if request.method == "GET":
            exposed = {
                "1080": {"file": preset_config["1080"]["file"]},
                "4k": {"file": preset_config["4k"]["file"]},
            }
            return jsonify(config=exposed)

        data = request.get_json(force=True) or {}
        changed = False

        for key in ("1080", "4k"):
            if key in data and isinstance(data[key], dict):
                current = preset_config.get(key)
                if not current:
                    continue
                file_val = data[key].get("file") or current["file"]
                name_val = current["name"]
                preset_config[key] = {"file": file_val, "name": name_val}
                changed = True

        if changed:
            save_preset_config()

        exposed = {
            "1080": {"file": preset_config["1080"]["file"]},
            "4k": {"file": preset_config["4k"]["file"]},
        }
        return jsonify(config=exposed)

    # ------------- preset uploads -------------

    @app.route("/api/presets/upload", methods=["POST"])
    def upload_preset_file():
        """Upload a HandBrake preset JSON file into PRESET_DIR."""
        if "preset_file" not in request.files:
            return jsonify(error="missing file field 'preset_file'"), 400

        f = request.files["preset_file"]
        if not f or f.filename == "":
            return jsonify(error="no file selected"), 400

        filename = secure_filename(f.filename)
        if not filename.lower().endswith(".json"):
            return jsonify(error="only .json preset files are supported"), 400

        contents = f.read()
        if not contents:
            return jsonify(error="empty file"), 400

        try:
            json.loads(contents.decode("utf-8") if isinstance(contents, bytes) else contents)
        except Exception:
            return jsonify(error="file is not valid JSON"), 400

        os.makedirs(PRESET_DIR, exist_ok=True)

        dest_path = os.path.join(PRESET_DIR, filename)
        try:
            with open(dest_path, "wb") as out_f:
                out_f.write(contents)
        except Exception as e:
            return jsonify(error=f"failed to save preset: {e}"), 500

        updated_files = list_preset_files()

        return jsonify(
            ok=True,
            filename=filename,
            preset_files=updated_files,
        )

    # ------------- Preset delete -------------

    @app.route("/api/presets/delete", methods=["POST"])
    def delete_preset_file():
        """Delete a HandBrake preset JSON file from PRESET_DIR."""
        data = request.get_json(force=True) or {}
        path = data.get("path") or ""
        if not path:
            return jsonify(error="missing 'path' for preset to delete"), 400

        real_target = os.path.realpath(path)
        real_root = os.path.realpath(PRESET_DIR)

        if not real_target.startswith(real_root + os.sep) and real_target != real_root:
            return jsonify(error="refusing to delete file outside preset directory"), 400

        if not os.path.isfile(real_target):
            return jsonify(error="preset file not found"), 404

        try:
            os.remove(real_target)
        except Exception as e:
            return jsonify(error=f"failed to delete preset: {e}"), 500

        updated_files = list_preset_files()
        return jsonify(
            ok=True,
            preset_files=updated_files,
        )

    # ------------------ preset download ----------------

    @app.route("/api/presets/download")
    def download_preset_file():
        """Download a preset JSON file from PRESET_DIR."""
        path = request.args.get("path") or ""
        if not path:
            return jsonify(error="missing 'path'"), 400

        real_target = os.path.realpath(path)
        real_root = os.path.realpath(PRESET_DIR)

        if not real_target.startswith(real_root + os.sep) and real_target != real_root:
            return jsonify(error="refusing to access file outside preset directory"), 400

        if not os.path.isfile(real_target):
            return jsonify(error="preset file not found"), 404

        return send_file(
            real_target,
            mimetype="application/json",
            as_attachment=True,
            download_name=os.path.basename(real_target),
        )

    # ------------- Queue state (pause / resume) -------------

    @app.route("/queue_state")
    def queue_state():
        """Return whether the dispatcher queue is paused."""
        paused = get_queue_state()
        return jsonify(paused=paused)

    @app.route("/pause_queue", methods=["POST"])
    def pause_queue():
        """Pause or resume the dispatcher queue."""
        data = request.get_json(silent=True) or {}
        if "paused" in data and isinstance(data["paused"], bool):
            new_state = set_queue_paused(data["paused"])
        else:
            new_state = set_queue_paused(None)
        return jsonify(paused=new_state)

    # ------------- Remove queued job -------------

    @app.route("/remove/<job_id>", methods=["POST"])
    def remove_job_route(job_id):
        """Remove a job from the queue if its status is still 'queued'."""
        ok, err = remove_queued_job(job_id)
        if not ok:
            return jsonify(error=err or "remove failed"), 400
        return jsonify(ok=True, job_id=job_id)

    @app.route("/move/<job_id>", methods=["POST"])
    def move_job_route(job_id):
        """Move a queued job up/down/top/bottom or to a specific position in the queue."""
        data = request.get_json(silent=True) or {}

        if "position" in data and data.get("position") not in (None, ""):
            ok, err = move_queued_job_to_position(job_id, data.get("position"))
            if not ok:
                return jsonify(error=err or "move failed"), 400
            return jsonify(ok=True, job_id=job_id, position=int(data.get("position")))

        direction = (data.get("direction") or "").strip().lower()
        ok, err = move_queued_job(job_id, direction)
        if not ok:
            return jsonify(error=err or "move failed"), 400
        return jsonify(ok=True, job_id=job_id, direction=direction)

    # ------------- Media search (files + folders, fuzzy-ish) -------------

    @app.route("/search_media")
    def search_media():
        """Search for video files AND folders by name."""
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify(error="missing 'q' search term"), 400

        base = (request.args.get("base") or "").strip()

        def normalize(s: str) -> str:
            s = s.lower()
            for ch in [".", "_", "-"]:
                s = s.replace(ch, " ")
            return " ".join(s.split())

        query_terms = normalize(q).split()
        if not query_terms:
            return jsonify(error="search term too short"), 400

        matches = []
        SEARCH_LIMIT = 200

        def name_matches(name: str) -> bool:
            n = normalize(name)
            return all(term in n for term in query_terms)

        def walk_root(root_path: str) -> bool:
            """Walk a single root path and collect up to SEARCH_LIMIT matches."""
            nonlocal matches

            if not os.path.isdir(root_path):
                return False

            for root_dir, dirs, files in os.walk(root_path):
                for d in dirs:
                    if not name_matches(d):
                        continue

                    full_path = os.path.join(root_dir, d)
                    if not is_allowed_path(full_path):
                        continue

                    matches.append(
                        {
                            "path": full_path,
                            "name": d,
                            "folder": root_dir,
                            "type": "dir",
                        }
                    )
                    if len(matches) >= SEARCH_LIMIT:
                        return True

                for name in files:
                    if not name.lower().endswith(VIDEO_EXTS):
                        continue
                    if not name_matches(name):
                        continue

                    full_path = os.path.join(root_dir, name)
                    if not is_allowed_path(full_path):
                        continue

                    matches.append(
                        {
                            "path": full_path,
                            "name": name,
                            "folder": root_dir,
                            "type": "file",
                        }
                    )
                    if len(matches) >= SEARCH_LIMIT:
                        return True

            return False

        if base:
            if not is_allowed_path(base) or not os.path.isdir(base):
                return jsonify(error="base path not allowed or not a directory"), 400
            walk_root(base)
        else:
            for root_path, _label in ROOTS:
                if walk_root(root_path):
                    break

        return jsonify(matches=matches, limit=SEARCH_LIMIT)
