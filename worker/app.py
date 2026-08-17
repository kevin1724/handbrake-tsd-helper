"""Minimal HTTP service for a transfer-only ByteSqueeze worker.

The controller owns the media library. A worker receives short-lived download
grants, stages sources under /work, runs HandBrake locally, and uploads results
to the controller. No media-library mount or browser UI is exposed.
"""

from __future__ import annotations

import os
import shutil
import time

from flask import Flask, jsonify, request

from webui.app.events import log_event
from webui.app.jobs import (
    create_remote_transfer_job,
    get_job_summary,
    initialize_jobs_system,
    list_jobs_for_api,
)
from webui.app.node_linking import (
    NODE_PROTOCOL_VERSION,
    accept_pairing,
    create_pairing_code,
    delete_trusted_controller,
    enable_pair_recovery,
    list_trusted_controllers_public,
    local_node_overview,
    node_discovery,
    recover_pairing,
    set_local_node_name,
    trusted_controller,
    update_trusted_controller,
    verify_hmac,
)
from webui.app.presets import guess_preset_from_filename, load_preset_config
from webui.app.settings import load_settings, save_settings


WORKER_RELEASE = "2.3.0"


def _public_encoding_policy() -> dict:
    settings = load_settings()
    return {
        "hardware_transcode_concurrency": int(
            settings.get("hardware_transcode_concurrency") or 1
        ),
        "software_transcode_concurrency": 1,
        "software_jobs_are_exclusive": True,
        "controller_managed": bool(
            settings.get("worker_controller_managed_capacity", False)
        ),
        "auto_stop_large_output_enabled": bool(
            settings.get("auto_stop_large_output_enabled", False)
        ),
        "auto_stop_large_output_percent": settings.get(
            "auto_stop_large_output_percent",
            90,
        ),
    }


def _apply_controller_encoding_policy(policy: dict | None) -> dict:
    policy = policy if isinstance(policy, dict) else {}
    allowed = {
        "hb_threads",
        "hardware_transcode_concurrency",
        "auto_stop_large_output_enabled",
        "auto_stop_large_output_percent",
    }
    updates = {key: policy[key] for key in allowed if key in policy}
    if "hardware_transcode_concurrency" in updates:
        updates["worker_controller_managed_capacity"] = True
    if updates:
        save_settings(updates)
    return _public_encoding_policy()


def _work_dir() -> str:
    return os.path.abspath(os.environ.get("TSD_WORKER_TEMP_DIR") or "/work/jobs")


def _pairing_ttl() -> int:
    try:
        value = int(os.environ.get("TSD_WORKER_PAIRING_TTL_SECONDS") or 3600)
    except (TypeError, ValueError):
        value = 3600
    return max(300, min(3600, value))


def _print_pairing_banner(pairing: dict) -> None:
    code = str(pairing.get("code") or "")
    expires_at = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(float(pairing.get("expires_at") or 0)))
    print("", flush=True)
    print("=" * 68, flush=True)
    print(" ByteSqueeze headless worker is ready", flush=True)
    print(f" Pairing code:  {code}", flush=True)
    print(f" Code expires:  {expires_at}", flush=True)
    print(" On the main server open Settings > Linked Workers,", flush=True)
    print(" enter this worker's URL and the code above, then click Pair.", flush=True)
    print(" No media drives are required. Temporary jobs use /work.", flush=True)
    print("=" * 68, flush=True)
    print("", flush=True)


def _request_scheme() -> str:
    value = str(request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip().lower()
    return value if value in {"http", "https"} else "http"


def _infer_controller_url() -> str:
    host = str(request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    if not host:
        return ""
    # Only the host can be inferred reliably. Controller pairing from the main
    # UI always sends window.location.origin, including its actual port.
    return f"{_request_scheme()}://{host}"


def _authenticated_controller():
    node_id = request.headers.get("X-Node-Id") or ""
    timestamp = request.headers.get("X-Node-Timestamp") or ""
    signature = request.headers.get("X-Node-Signature") or ""
    controller = trusted_controller(node_id)
    if not controller:
        return None
    body_bytes = request.get_data(cache=True) or b""
    if not verify_hmac(
        request.method,
        request.path,
        body_bytes,
        node_id=node_id,
        token=str(controller.get("token") or ""),
        timestamp=timestamp,
        signature=signature,
    ):
        return None
    update_trusted_controller(node_id, {"last_seen": time.time()})
    return controller


def create_worker_app(*, announce_pairing: bool = True) -> Flask:
    """Create the worker-only Flask application."""
    app = Flask(__name__)
    work_dir = _work_dir()
    os.makedirs(work_dir, exist_ok=True)

    worker_name = str(os.environ.get("TSD_WORKER_NAME") or "ByteSqueeze Worker").strip()[:80]
    set_local_node_name(worker_name)
    save_settings({"remote_transfer_temp_dir": work_dir})
    load_preset_config()
    initialize_jobs_system()

    if announce_pairing:
        pairing = create_pairing_code(ttl_seconds=_pairing_ttl())
        _print_pairing_banner(pairing)

    @app.get("/")
    def worker_root():
        local = local_node_overview()
        return jsonify(
            ok=True,
            service="bytesqueeze-headless-worker",
            release=WORKER_RELEASE,
            node_id=local.get("id"),
            node_name=local.get("name"),
            paired=bool(local.get("paired_controller_count")),
            encoding_policy=_public_encoding_policy(),
            message="Headless worker only. Pairing code is printed in docker logs.",
        )

    @app.get("/api/health")
    def worker_health():
        usage = shutil.disk_usage(work_dir)
        summary = get_job_summary()
        return jsonify(
            ok=True,
            status="healthy",
            release=WORKER_RELEASE,
            service="bytesqueeze-headless-worker",
            work={"path": work_dir, "free_bytes": int(usage.free), "total_bytes": int(usage.total)},
            queue=summary,
            encoding_policy=_public_encoding_policy(),
        )

    @app.get("/api/node/discovery")
    def worker_discovery():
        return jsonify(ok=True, **node_discovery())

    @app.post("/api/node/pair/accept")
    def worker_pair_accept():
        data = request.get_json(silent=True) or {}
        if not str(data.get("controller_url") or "").strip():
            data["controller_url"] = _infer_controller_url()
        try:
            accepted = accept_pairing(data.get("code") or "", data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        accepted["capabilities"] = node_discovery().get("capabilities") or []
        print(
            f"[WORKER] Paired with controller {data.get('controller_name') or data.get('controller_id')} "
            f"at {accepted.get('controller_url') or data.get('controller_url')}",
            flush=True,
        )
        log_event("node_paired", "Controller paired with this headless worker.", level="info")
        return jsonify(ok=True, worker_mode="headless", requires_remote_transfer=True, **accepted)

    @app.post("/api/node/pair/recover")
    def worker_pair_recover():
        data = request.get_json(silent=True) or {}
        if not str(data.get("controller_url") or "").strip():
            data["controller_url"] = _infer_controller_url()
        try:
            recovered = recover_pairing(data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 401
        recovered["capabilities"] = node_discovery().get("capabilities") or []
        return jsonify(ok=True, worker_mode="headless", requires_remote_transfer=True, **recovered)

    @app.post("/api/node/pair/enable-recovery")
    def worker_enable_recovery():
        controller = _authenticated_controller()
        if not controller:
            return jsonify(error="unauthorized"), 401
        try:
            token = enable_pair_recovery(str(controller.get("id") or ""))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True, recovery_token=token)

    @app.get("/api/node/status")
    def worker_status():
        controller = _authenticated_controller()
        if not controller:
            return jsonify(error="unauthorized"), 401
        local = local_node_overview()
        usage = shutil.disk_usage(work_dir)
        discovery = node_discovery()
        return jsonify(
            ok=True,
            release=WORKER_RELEASE,
            id=local.get("id"),
            name=local.get("name"),
            role="worker",
            role_label="Headless transfer worker",
            worker_mode="headless",
            requires_remote_transfer=True,
            protocol_version=NODE_PROTOCOL_VERSION,
            capabilities=discovery.get("capabilities") or [],
            paired_controllers=list_trusted_controllers_public(),
            remote_transfer_temp_dir=work_dir,
            work_free_bytes=int(usage.free),
            summary=get_job_summary(),
            jobs=list_jobs_for_api(),
            encoding_policy=_public_encoding_policy(),
            prediction_profile={},
        )

    @app.post("/api/node/config")
    def worker_controller_config():
        controller = _authenticated_controller()
        if not controller:
            return jsonify(error="unauthorized"), 401
        policy = request.get_json(silent=True) or {}
        if not any(
            key in policy
            for key in (
                "hb_threads",
                "hardware_transcode_concurrency",
                "auto_stop_large_output_enabled",
                "auto_stop_large_output_percent",
            )
        ):
            return jsonify(error="no supported worker settings supplied"), 400
        applied = _apply_controller_encoding_policy(policy)
        log_event(
            "worker_capacity_updated",
            f"{controller.get('name') or 'Controller'} set this worker to "
            f"{applied['hardware_transcode_concurrency']} GPU slot(s).",
            level="info",
        )
        return jsonify(ok=True, encoding_policy=applied)

    @app.post("/api/node/jobs")
    def worker_receive_jobs():
        controller = _authenticated_controller()
        if not controller:
            return jsonify(error="unauthorized"), 401
        payload = request.get_json(silent=True) or {}
        jobs_payload = payload.get("jobs")
        if not isinstance(jobs_payload, list):
            return jsonify(error="missing jobs"), 400
        applied_policy = _apply_controller_encoding_policy(
            payload.get("encoding_policy")
        )

        count = 0
        skipped = []
        for job in jobs_payload:
            if not isinstance(job, dict):
                continue
            transfer = job.get("transfer") if isinstance(job.get("transfer"), dict) else {}
            src = str(job.get("src") or transfer.get("original_path") or transfer.get("source_basename") or "").strip()
            if not transfer:
                skipped.append({"path": src, "reason": "headless worker requires remote transfer"})
                continue
            missing = [
                key
                for key in ("source_url", "upload_url", "download_token", "upload_token", "worker_node_id")
                if not str(transfer.get(key) or "").strip()
            ]
            if missing:
                skipped.append({"path": src, "reason": f"missing transfer data: {', '.join(missing)}"})
                continue
            transfer["remote_temp_dir"] = work_dir
            preset = str(job.get("preset") or "auto").strip().lower()
            if preset not in {"auto", "1080", "4k"}:
                preset = "auto"
            effective = guess_preset_from_filename(os.path.basename(src)) if preset == "auto" else preset
            _job_id, created = create_remote_transfer_job(
                src,
                effective,
                transfer,
                extra_args=str(job.get("extra_args") or ""),
                preset_bundle=job.get("preset_bundle"),
                encode_metadata=job.get("encode_metadata") if isinstance(job.get("encode_metadata"), dict) else None,
                encoding_policy=job.get("encoding_policy") if isinstance(job.get("encoding_policy"), dict) else None,
            )
            count += 1 if created else 0

        print(f"[WORKER] Accepted {count} remote job(s); skipped {len(skipped)}.", flush=True)
        log_event("node_jobs_received", f"Received {count} headless worker job(s).", level="info")
        return jsonify(
            ok=True,
            count=count,
            skipped=skipped,
            summary=get_job_summary(),
            encoding_policy=applied_policy,
        )

    @app.post("/api/node/rotate_secret")
    def worker_rotate_secret():
        controller = _authenticated_controller()
        if not controller:
            return jsonify(error="unauthorized"), 401
        data = request.get_json(silent=True) or {}
        new_token = str(data.get("token") or "").strip()
        if len(new_token) < 24:
            return jsonify(error="invalid token"), 400
        update_trusted_controller(controller["id"], {"token": new_token})
        return jsonify(ok=True)

    @app.post("/api/node/unlink")
    def worker_unlink():
        controller = _authenticated_controller()
        if not controller:
            return jsonify(error="unauthorized"), 401
        delete_trusted_controller(controller["id"])
        pairing = create_pairing_code(ttl_seconds=_pairing_ttl())
        _print_pairing_banner(pairing)
        return jsonify(ok=True)

    return app
