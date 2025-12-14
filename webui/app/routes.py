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


# -------------------------------------------------------------------
# Side-by-side preview helpers
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# Route registration
# -------------------------------------------------------------------

def register_routes(app):
    """Attach all routes to the given Flask app."""

    # ------------- UI -------------

    @app.route("/")
    def index():
        """Render the main single-page web UI."""
        preset_files = list_preset_files()
        return render_template(
            "index.html",
            roots=ROOTS,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
        )

    @app.route("/size_wizard")
    def size_wizard_page():
        """Render the Size Wizard page (prefill via query string)."""
        return render_template("size_wizard.html")

    @app.route("/settings")
    def settings_page():
        """Render the settings page (global app settings)."""
        settings = load_settings()
        preset_files = list_preset_files()
        return render_template(
            "settings.html",
            settings=settings,
            preset_files=preset_files,
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
        """Queue an encode with target size + simple quality tweaks."""
        data = request.get_json(force=True)

        src = data.get("src")
        preset = data.get("preset") or "auto"
        size_value = data.get("target_size_value")
        if size_value in (None, "", 0):
            size_value = 5
        size_unit = (data.get("target_size_unit") or "GB").upper()
        quality = data.get("quality") or "balanced"
        allow_downscale = bool(data.get("allow_downscale", True))
        force_4k = bool(data.get("force_4k", False))

        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400
        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400
        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400
        if size_unit not in ("MB", "GB"):
            return jsonify(error="invalid target_size_unit"), 400
        if quality not in ("high", "balanced", "small"):
            return jsonify(error="invalid quality"), 400
        try:
            size_value_f = float(size_value)
        except Exception:
            return jsonify(error="invalid target_size_value"), 400
        if size_value_f <= 0:
            return jsonify(error="invalid target_size_value"), 400

        base = os.path.basename(src)
        name_only, _ext = os.path.splitext(base)
        if name_only.lower().endswith("-tsd"):
            return jsonify(error="file already tagged -TSD, not queuing"), 400

        if preset == "auto":
            preset = guess_preset_from_filename(base)

        target_mb = size_value_f * (1024.0 if size_unit == "GB" else 1.0)

        extra_args = [f"--target-size {int(target_mb)}"]
        if quality == "high":
            extra_args.append("--encoder-preset slow")
        elif quality == "balanced":
            extra_args.append("--encoder-preset medium")
        else:
            extra_args.append("--encoder-preset fast")

        # Optional downscale logic (same heuristic as wizard_preview)
        try:
            info = _probe_media(src)
            duration_sec = float(info.get("duration_sec") or 0.0)
            src_w = int(info.get("width") or 0)
            src_h = int(info.get("height") or 0)
            fps = float(info.get("fps") or 0.0) or 24.0

            if duration_sec > 0 and src_w > 0 and src_h > 0 and (not force_4k) and allow_downscale:
                target_bytes = target_mb * 1024.0 * 1024.0
                total_bitrate_kbps = (target_bytes * 8.0 / duration_sec) / 1000.0
                audio_kbps = _quality_audio_kbps(quality)
                video_kbps = max(250.0, total_bitrate_kbps - audio_kbps)

                bpp_src = _bpp(video_kbps, src_w, src_h, fps)

                if src_h > 1080 and bpp_src < 0.045:
                    scale = 1080 / float(src_h)
                    out_w = int((src_w * scale) // 2 * 2)
                    out_h = int((src_h * scale) // 2 * 2)
                    out_w = max(2, out_w)
                    out_h = max(2, out_h)

                    bpp_1080 = _bpp(video_kbps, out_w, out_h, fps)
                    if bpp_1080 >= bpp_src * 1.6:
                        extra_args.append(f"--width {out_w} --height {out_h}")
        except Exception:
            pass

        job_id = create_job(src, preset, extra_args=" ".join(extra_args))
        return jsonify(job_id=job_id, preset=preset, extra_args=extra_args)

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
    @app.route("/wizard_preview", methods=["POST"])
    def wizard_preview():
        """Return an estimated outcome for Size Wizard inputs."""
        data = request.get_json(force=True) or {}
        src = data.get("src")
        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400
        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400

        try:
            size_value = float(data.get("target_size_value") or 5.0)
        except Exception:
            return jsonify(error="invalid target_size_value"), 400
        unit = (data.get("target_size_unit") or "GB").upper()
        if unit not in ("GB", "MB"):
            return jsonify(error="invalid target_size_unit"), 400
        if size_value <= 0:
            return jsonify(error="invalid target_size_value"), 400

        quality = (data.get("quality") or "balanced").lower()
        if quality not in ("high", "balanced", "small"):
            return jsonify(error="invalid quality"), 400

        allow_downscale = bool(data.get("allow_downscale", True))
        force_4k = bool(data.get("force_4k", False))

        try:
            info = _probe_media(src)
        except Exception as e:
            return jsonify(error=str(e)), 500

        duration_sec = float(info.get("duration_sec") or 0.0)
        src_w = int(info.get("width") or 0)
        src_h = int(info.get("height") or 0)
        fps = float(info.get("fps") or 0.0) or 24.0
        if duration_sec <= 0 or src_w <= 0 or src_h <= 0:
            return jsonify(error="probe incomplete"), 500

        target_mb = _size_to_mb(size_value, unit)
        target_bytes = target_mb * 1024.0 * 1024.0

        total_bitrate_kbps = (target_bytes * 8.0 / duration_sec) / 1000.0
        audio_kbps = _quality_audio_kbps(quality)
        video_kbps = max(250.0, total_bitrate_kbps - audio_kbps)

        enc_preset = _preset_from_quality(quality)

        out_w, out_h = src_w, src_h
        decision = "keep"
        note = ""

        bpp_src = _bpp(video_kbps, src_w, src_h, fps)

        def pick_downscale(w, h):
            if w <= 0 or h <= 0:
                return (w, h)
            target_h = 1080
            if h <= target_h:
                return (w, h)
            scale = target_h / float(h)
            nw = int((w * scale) // 2 * 2)
            nh = int((h * scale) // 2 * 2)
            return (max(2, nw), max(2, nh))

        cand_w, cand_h = pick_downscale(src_w, src_h)
        bpp_1080 = _bpp(video_kbps, cand_w, cand_h, fps) if (cand_w, cand_h) != (src_w, src_h) else bpp_src

        if (not force_4k) and allow_downscale:
            if src_h > 1080 and bpp_src < 0.045 and bpp_1080 >= bpp_src * 1.6:
                out_w, out_h = cand_w, cand_h
                decision = "downscale"
                note = "Requested size implies low bitrate for 4K; downscaling to improve quality."

        bpp_final = _bpp(video_kbps, out_w, out_h, fps)
        q_code, q_label = _quality_label_from_bpp(bpp_final)

        est_fps = _estimate_encode_fps(out_w, out_h, enc_preset)
        total_frames = duration_sec * fps
        eta_sec = total_frames / est_fps if est_fps > 0 else 0.0

        extra_args = [f"--target-size {int(target_mb)}", f"--encoder-preset {enc_preset}"]
        if decision == "downscale":
            extra_args.append(f"--width {out_w} --height {out_h}")

        return jsonify(
            src=src,
            probe=info,
            inputs={
                "target_mb": target_mb,
                "quality": quality,
                "allow_downscale": allow_downscale,
                "force_4k": force_4k,
            },
            estimates={
                "total_bitrate_kbps": round(total_bitrate_kbps, 1),
                "audio_bitrate_kbps": audio_kbps,
                "video_bitrate_kbps": round(video_kbps, 1),
                "bpp": round(bpp_final, 5),
                "quality_code": q_code,
                "quality_label": q_label,
                "eta_seconds": int(round(eta_sec)),
                "eta_human": f"{int(eta_sec//3600)}h {int((eta_sec%3600)//60)}m" if eta_sec >= 3600 else f"{int(eta_sec//60)}m",
                "est_fps": round(est_fps, 1),
                "decision": decision,
                "decision_note": note,
                "output_resolution": {"width": out_w, "height": out_h},
            },
            suggested_extra_args=extra_args,
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