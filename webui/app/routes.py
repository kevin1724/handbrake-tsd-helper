"""
Flask route definitions for HandBrake TSD Helper.

This module:
- Defines all HTTP endpoints (API + web UI)
- Uses helpers from jobs.py and presets.py
- Renders the single-page Web UI (index.html template)
"""

import os
import json

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
# Route registration
# -------------------------------------------------------------------

def register_routes(app):
    """
    Attach all routes to the given Flask app.
    """

    # ------------- UI -------------

    @app.route("/")
    def index():
        """
        Render the main single-page web UI.

        Passes:
        - roots: list of allowed media roots
        - preset_files: .json preset files discovered in PRESET_DIR
        - preset_dir: path to preset folder inside the container
        """
        preset_files = list_preset_files()
        return render_template(
            "index.html",
            roots=ROOTS,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
        )

    @app.route("/settings")
    def settings_page():
        """
        Render the settings page (global app settings).

        Currently supports:
        - HandBrake thread (CPU core) count (hb_threads)
        """
        settings = load_settings()
        preset_files = list_preset_files() 
        return render_template(
            "settings.html",
            settings=settings,
            preset_files=preset_files,
        )

    @app.route("/debug_config")
    def debug_config():
        """
        Simple debug endpoint so we can see what the backend thinks
        the roots and preset files are.
        """
        preset_files = list_preset_files()
        return jsonify(
            roots=ROOTS,
            preset_files=preset_files,
            preset_dir=PRESET_DIR,
        )

    # ------------- Global settings (JSON API) -------------

    @app.route("/api/settings", methods=["GET", "POST"])
    def settings_api():
        """
        GET  → return current settings (e.g., hb_threads)
        POST → update settings; expected JSON body like:
            { "hb_threads": 8 }

        Returns:
        { "settings": {...} }
        """
        if request.method == "GET":
            settings = load_settings()
            return jsonify(settings=settings)

        data = request.get_json(silent=True) or {}
        new_settings = save_settings(data)
        return jsonify(settings=new_settings)

    # ------------- Directory listing -------------

    @app.route("/list")
    def list_path():
        """
        List folders + video files for a given path (used by the browser UI).
        """
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
        """
        Queue a single file for encoding.
        Body JSON:
        {
          "src": "/full/path/to/file.mkv",
          "preset": "1080" | "4k" | "auto"
        }
        """
        data = request.get_json(force=True)
        src = data.get("src")
        preset = data.get("preset") or "1080"

        if not src or not os.path.isfile(src):
            return jsonify(error="invalid src"), 400

        if not is_allowed_path(src):
            return jsonify(error="path not allowed"), 400

        if preset not in ("1080", "4k", "auto"):
            return jsonify(error="invalid preset"), 400

        # Skip files that already have -TSD in the base name
        base = os.path.basename(src)
        name_only, ext = os.path.splitext(base)
        if name_only.lower().endswith("-tsd"):
            return jsonify(error="file already tagged -TSD, not queuing"), 400

        # Auto-detect preset from filename if requested
        if preset == "auto":
            preset = guess_preset_from_filename(base)

        job_id = create_job(src, preset)
        return jsonify(job_id=job_id)

    # ------------- Job status -------------

    @app.route("/status/<job_id>")
    def status(job_id):
        """
        Return status + recent log for a specific job.
        """
        job = get_job(job_id)
        if not job:
            return jsonify(error="job not found"), 404
        return jsonify(job)

    # ------------- Cancel job -------------

    @app.route("/cancel/<job_id>", methods=["POST"])
    def cancel_route(job_id):
        """
        Cancel a running job or mark a queued one as canceled.
        """
        ok, err = cancel_job(job_id)
        if not ok:
            return jsonify(error=err or "cancel failed"), 400
        return jsonify(ok=True, job_id=job_id)

    # ------------- Job list -------------

    @app.route("/jobs")
    def jobs_list():
        """
        Return a simplified list of all jobs for the history table.
        """
        items = list_jobs_for_api()
        return jsonify(jobs=items)

    # ------------- Job log download -------------

    @app.route("/job_log/<job_id>")
    def job_log(job_id):
        """
        Download the full log file for a given job.
        """
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
        """
        Rename all video files in a directory to add -TSD before the extension.
        Body JSON:
        {
          "path": "/some/folder"
        }
        """
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
                # Skip already -TSD tagged
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
        """
        Queue encode jobs for all video files in a folder (non-recursive).
        Body JSON:
        {
          "path": "/some/folder",
          "preset": "1080" | "4k" | "auto"
        }
        """
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
            if preset == "auto":
                effective_preset = guess_preset_from_filename(entry)
            else:
                effective_preset = preset
            to_create.append((src, effective_preset))

        count = create_jobs_batch(to_create)
        return jsonify(count=count)

    # ------------- Batch encode (recursive) -------------

    @app.route("/batch_encode_recursive", methods=["POST"])
    def batch_encode_recursive():
        """
        Queue encode jobs for all video files in a folder and all subfolders.
        Body JSON:
        {
          "path": "/some/folder",
          "preset": "1080" | "4k" | "auto"
        }
        """
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
        for root, dirs, files in os.walk(path):
            for entry in files:
                if not entry.lower().endswith(VIDEO_EXTS):
                    continue

                name, ext = os.path.splitext(entry)
                if name.lower().endswith("-tsd"):
                    continue

                src = os.path.join(root, entry)
                if preset == "auto":
                    effective_preset = guess_preset_from_filename(entry)
                else:
                    effective_preset = preset

                to_create.append((src, effective_preset))

        if not to_create:
            return jsonify(error="no video files found"), 400

        count = create_jobs_batch(to_create)
        return jsonify(count=count)

    # ------------- Clear finished jobs -------------

    @app.route("/clear_finished_jobs", methods=["POST"])
    def clear_finished_jobs_route():
        """
        Delete all finished jobs (done/error) from history and remove their logs.
        """
        removed = clear_finished_jobs_core()
        return jsonify(removed=removed)

    # ------------- Preset config (1080 / 4k mapping) -------------

    @app.route("/preset_config", methods=["GET", "POST"])
    def preset_config_route():
        """
        Get or update default preset files for 1080 and 4K.

        GET → { config: { "1080": {"file":...}, "4k": {"file":...} } }

        POST body:
        {
          "1080": {"file": "/presets/some-1080.json"},
          "4k":   {"file": "/presets/some-4k.json"}
        }
        """
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
                name_val = current["name"]  # keep existing fallback name
                preset_config[key] = {"file": file_val, "name": name_val}
                changed = True

        if changed:
            save_preset_config()

        exposed = {
            "1080": {"file": preset_config["1080"]["file"]},
            "4k": {"file": preset_config["4k"]["file"]},
        }
        return jsonify(config=exposed)



    # ------------- preset uploads-------------

    @app.route("/api/presets/upload", methods=["POST"])
    def upload_preset_file():
        """
        Upload a HandBrake preset JSON file into PRESET_DIR.

        Expects multipart/form-data with:
          - field name: "preset_file"
          - file name ending in .json

        On success:
          { "ok": true,
            "filename": "<basename>.json",
            "preset_files": [ "<full paths...>" ]
          }
        """
        if "preset_file" not in request.files:
            return jsonify(error="missing file field 'preset_file'"), 400

        f = request.files["preset_file"]
        if not f or f.filename == "":
            return jsonify(error="no file selected"), 400

        # Sanitize filename
        filename = secure_filename(f.filename)
        if not filename.lower().endswith(".json"):
            return jsonify(error="only .json preset files are supported"), 400

        # Read file content once (so we can both validate JSON and save it)
        contents = f.read()
        if not contents:
            return jsonify(error="empty file"), 400

        # Basic JSON validation – just make sure it's valid JSON.
        try:
            json.loads(contents.decode("utf-8") if isinstance(contents, bytes) else contents)
        except Exception:
            return jsonify(error="file is not valid JSON"), 400

        # Ensure preset directory exists
        os.makedirs(PRESET_DIR, exist_ok=True)

        dest_path = os.path.join(PRESET_DIR, filename)
        try:
            with open(dest_path, "wb") as out:
                out.write(contents)
        except Exception as e:
            return jsonify(error=f"failed to save preset: {e}"), 500

        # Re-scan presets so UI can refresh if it wants to
        updated_files = list_preset_files()

        return jsonify(
            ok=True,
            filename=filename,
            preset_files=updated_files,
        )

    # ------------- Preset delete -------------
    @app.route("/api/presets/delete", methods=["POST"])
    def delete_preset_file():
        """
        Delete a HandBrake preset JSON file from PRESET_DIR.

        Expects JSON body:
        {
          "path": "/app/presets/4kPlex.json"   # full path as returned by list_preset_files()
        }

        Safety:
        - Only allows deleting files under PRESET_DIR
        - Fails if file does not exist
        """
        data = request.get_json(force=True) or {}
        path = data.get("path") or ""
        if not path:
            return jsonify(error="missing 'path' for preset to delete"), 400

        # Resolve real paths to avoid traversal tricks
        real_target = os.path.realpath(path)
        real_root = os.path.realpath(PRESET_DIR)

        # Ensure the file is inside PRESET_DIR
        if not real_target.startswith(real_root + os.sep) and real_target != real_root:
            return jsonify(error="refusing to delete file outside preset directory"), 400

        if not os.path.isfile(real_target):
            return jsonify(error="preset file not found"), 404

        try:
            os.remove(real_target)
        except Exception as e:
            return jsonify(error=f"failed to delete preset: {e}"), 500

        # Return updated list so UI can refresh
        updated_files = list_preset_files()
        return jsonify(
            ok=True,
            preset_files=updated_files,
        )


# ------------------ preset download ----------------

    @app.route("/api/presets/download")
    def download_preset_file():
        """
        Download a preset JSON file from PRESET_DIR.

        Query params:
          ?path=/full/path/to/preset.json  (must be under PRESET_DIR)
        """
        path = request.args.get("path") or ""
        if not path:
            return jsonify(error="missing 'path'"), 400

        real_target = os.path.realpath(path)
        real_root = os.path.realpath(PRESET_DIR)

        # Ensure target is inside PRESET_DIR
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
        """
        Return whether the dispatcher queue is paused.
        """
        paused = get_queue_state()
        return jsonify(paused=paused)

    @app.route("/pause_queue", methods=["POST"])
    def pause_queue():
        """
        Pause or resume the dispatcher queue.

        Body JSON:
        { "paused": true }  → force pause
        { "paused": false } → force resume
        { } or { "paused": null } → toggle
        """
        data = request.get_json(silent=True) or {}
        if "paused" in data and isinstance(data["paused"], bool):
            new_state = set_queue_paused(data["paused"])
        else:
            new_state = set_queue_paused(None)
        return jsonify(paused=new_state)

    # ------------- Remove queued job -------------

    @app.route("/remove/<job_id>", methods=["POST"])
    def remove_job_route(job_id):
        """
        Remove a job from the queue if its status is still 'queued'.
        """
        ok, err = remove_queued_job(job_id)
        if not ok:
            return jsonify(error=err or "remove failed"), 400
        return jsonify(ok=True, job_id=job_id)
