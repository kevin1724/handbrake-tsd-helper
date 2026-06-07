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
        "-show_entries", "format=duration:stream=width,height,r_frame_rate",
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

    return {
        "duration_sec": duration_sec,
        "width": width,
        "height": height,
        "fps": fps or 24.0,
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

    return {
        "duration_sec": float(dur),
        "width": int(w),
        "height": int(h),
        "fps": float(fps),
        "video_codec": codec,
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

WIZARD_DEFAULT_OPTIONS = {
    "preset": "auto",
    "target_size_value": 5.0,
    "target_size_unit": "GB",
    "quality": "balanced",
    "video_codec": "h265",
    "encoder_family": "software",
    "bit_depth": "10",
    "encoder_speed": "auto",
    "resolution_mode": "auto",
    "audio_mode": "auto",
    "audio_bitrate": "auto",
    "audio_tracks": "first",
    "subtitle_mode": "none",
    "framerate_mode": "same",
    "framerate": "23.976",
    "deinterlace": "off",
    "crop_mode": "auto",
    "two_pass": False,
}


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


def _wizard_normalize_options(data: dict) -> dict:
    data = data or {}
    options = WIZARD_DEFAULT_OPTIONS.copy()

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
            "preset": preset,
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
        if options["audio_tracks"] == "all":
            args.append("--all-audio")

        if options["audio_mode"] == "copy":
            args += ["-E", "copy"]
        else:
            args += ["-E", "av_aac", "-B", str(_wizard_audio_kbps(options))]

        if options["subtitle_mode"] == "first":
            args += ["--subtitle", "1"]
        elif options["subtitle_mode"] == "all":
            args.append("--all-subtitles")

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

    info = probe_func(src)
    duration_sec = float(info.get("duration_sec") or 0.0)
    src_w = int(info.get("width") or 0)
    src_h = int(info.get("height") or 0)
    fps = float(info.get("fps") or 0.0) or 24.0
    if duration_sec <= 0 or src_w <= 0 or src_h <= 0:
        raise RuntimeError("probe incomplete")

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

    settings = load_settings()
    cpu = get_cpu_profile(settings.get("cpu_profile"))
    try:
        cpu_override_f = float(settings.get("cpu_speed_override", 1.0))
    except Exception:
        cpu_override_f = 1.0
    if cpu_override_f <= 0:
        cpu_override_f = 1.0

    base_est_fps = _estimate_encode_fps(out_w, out_h, encoder_preset)
    if options["encoder_family"] == "qsv":
        base_est_fps *= 3.0
    est_fps = max(1.0, min(base_est_fps * float(cpu.speed_index) * cpu_override_f, 500.0))
    eta_sec = (duration_sec * fps) / est_fps if est_fps > 0 else 0.0

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
            "eta_seconds": int(round(eta_sec)),
            "eta_human": f"{int(eta_sec//3600)}h {int((eta_sec%3600)//60)}m" if eta_sec >= 3600 else f"{int(eta_sec//60)}m",
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
    return _wizard_normalize_options(options)


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
        new_settings = save_settings(data)
        return jsonify(settings=new_settings)

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

        return jsonify(path=path, dirs=dirs, files=files)

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
