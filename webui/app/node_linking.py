from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import time
import uuid
from copy import deepcopy
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import DATA_DIR


NODE_LINK_FILE = os.path.join(DATA_DIR.rstrip("/"), "linked_nodes.json")
NODE_TRANSFER_FILE = os.path.join(DATA_DIR.rstrip("/"), "node_transfers.json")
PAIRING_TTL_SECONDS = 15 * 60
PAIRING_RETRY_GRACE_SECONDS = 5 * 60
HEARTBEAT_WARN_SECONDS = 2 * 60
HEARTBEAT_STALE_SECONDS = 10 * 60
HEARTBEAT_RUNNING_GRACE_SECONDS = 2 * 60 * 60
HEARTBEAT_MAX_MISSES = 3
TRANSFER_TTL_SECONDS = 48 * 60 * 60
NODE_STATE_SCHEMA_VERSION = 2
NODE_PROTOCOL_VERSION = 2
NODE_CAPABILITIES = [
    "heartbeat",
    "pair-recovery",
    "remote-transfer",
    "preset-bundle",
    "job-dispatch",
    "diagnostics",
    "controller-encoding-policy",
    "gpu-multi-encode",
    "cpu-software-exclusive",
    "output-size-guard",
    "remote-job-logs",
    "observed-controller-route",
    "resilient-transfer-download",
]
STATE_LOCK = threading.RLock()
TRANSFER_LOCK = threading.RLock()


def _now() -> float:
    return time.time()


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _empty_state() -> dict:
    return {
        "schema_version": NODE_STATE_SCHEMA_VERSION,
        "local_node_id": uuid.uuid4().hex,
        "local_node_name": "HandBrake TSD Node",
        "pairing": {},
        "trusted_controllers": {},
        "nodes": {},
        "updated_at": 0,
    }


def _normalize_state(data) -> dict:
    if not isinstance(data, dict):
        data = _empty_state()

    data["schema_version"] = NODE_STATE_SCHEMA_VERSION
    data.setdefault("local_node_id", uuid.uuid4().hex)
    data.setdefault("local_node_name", "HandBrake TSD Node")
    data.setdefault("pairing", {})
    data.setdefault("trusted_controllers", {})
    data.setdefault("nodes", {})
    data.setdefault("updated_at", 0)
    return data


def _load_state_unlocked() -> dict:
    data = None
    for path in (NODE_LINK_FILE, NODE_LINK_FILE + ".bak"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                candidate = json.load(f)
            if isinstance(candidate, dict):
                data = candidate
                break
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return _normalize_state(data if isinstance(data, dict) else _empty_state())


def _write_json_atomic(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or DATA_DIR, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _save_state_unlocked(data: dict) -> None:
    data["schema_version"] = NODE_STATE_SCHEMA_VERSION
    data["updated_at"] = _now()
    _write_json_atomic(NODE_LINK_FILE, data)
    try:
        shutil.copy2(NODE_LINK_FILE, NODE_LINK_FILE + ".bak")
    except OSError:
        # The primary file is already durable. A backup failure on a NAS must
        # not turn a successful pairing or heartbeat into an HTTP 500.
        pass


def _load_state() -> dict:
    with STATE_LOCK:
        data = _load_state_unlocked()
        if not os.path.exists(NODE_LINK_FILE):
            _save_state_unlocked(data)
        return deepcopy(data)


def _save_state(data: dict) -> None:
    with STATE_LOCK:
        _save_state_unlocked(_normalize_state(data))


def _mutate_state(mutator):
    """Run one read/modify/write transaction under the process state lock."""
    with STATE_LOCK:
        data = _load_state_unlocked()
        result = mutator(data)
        _save_state_unlocked(data)
        return deepcopy(result)


def local_node_info() -> dict:
    data = _load_state()
    return {
        "id": data.get("local_node_id"),
        "name": data.get("local_node_name") or "HandBrake TSD Node",
    }


def node_discovery() -> dict:
    local = local_node_info()
    headless = str(os.environ.get("TSD_WORKER_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
    capabilities = list(NODE_CAPABILITIES)
    if headless:
        capabilities.extend(["headless-worker", "remote-transfer-only"])
    return {
        "service": "handbrake-tsd-node",
        "node_id": local["id"],
        "node_name": local["name"],
        "protocol_version": NODE_PROTOCOL_VERSION,
        "state_schema_version": NODE_STATE_SCHEMA_VERSION,
        "capabilities": capabilities,
        "worker_mode": "headless" if headless else "full",
        "requires_remote_transfer": headless,
        "recommended_transfer_mode": "remote" if headless else "auto",
        "pairing": {
            "code_format": "XXXXX-XXXXX",
            "idempotent_retry_seconds": PAIRING_RETRY_GRACE_SECONDS,
        },
    }


def set_local_node_name(name: str) -> dict:
    value = str(name or "").strip()[:80] or "HandBrake TSD Node"
    _mutate_state(lambda data: data.update({"local_node_name": value}))
    return local_node_info()


def _hash_pairing_code(code: str) -> str:
    return hashlib.sha256(str(code or "").encode("utf-8", errors="ignore")).hexdigest()


def _hash_secret(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def normalize_transfer_mode(value: str) -> str:
    mode = str(value or "local").strip().lower()
    if mode in {"auto", "automatic", "local_then_remote", "fallback"}:
        return "auto"
    if mode in {"remote", "remote_transfer", "transfer"}:
        return "remote"
    return "local"


def normalize_hardware_transcode_concurrency(value, default: int = 1) -> int:
    """Return the safe GPU slot count stored by the controller per worker."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default or 1)
    return max(1, min(8, parsed))


def node_has_running_work(row: dict) -> bool:
    row = row if isinstance(row, dict) else {}
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    try:
        if int(counts.get("running") or 0) > 0 or int(counts.get("waiting_to_upload") or 0) > 0:
            return True
    except Exception:
        pass
    jobs = row.get("jobs") if isinstance(row.get("jobs"), list) else []
    return any(str(job.get("status") or "").lower() in {"running", "waiting_to_upload"} for job in jobs if isinstance(job, dict))


def heartbeat_allowed_age(row: dict) -> int:
    return HEARTBEAT_RUNNING_GRACE_SECONDS if node_has_running_work(row) else HEARTBEAT_STALE_SECONDS


def create_pairing_code(ttl_seconds: int = PAIRING_TTL_SECONDS) -> dict:
    # Human-friendly Crockford-style code: easy to type and avoids 0/O/1/I.
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    raw = "".join(secrets.choice(alphabet) for _ in range(10))
    code = f"{raw[:5]}-{raw[5:]}"
    expires_at = _now() + max(60, min(3600, int(ttl_seconds or PAIRING_TTL_SECONDS)))

    def apply(data):
        data["pairing"] = {
            "code_hash": _hash_pairing_code(code),
            "expires_at": expires_at,
            "created_at": _now(),
            "used_at": 0,
            "used_by_controller_id": "",
            "attempt_count": 0,
        }

    _mutate_state(apply)
    return {"code": code, "expires_at": expires_at}


def accept_pairing(code: str, controller: dict) -> dict:
    normalized_code = str(code or "").strip().upper()
    controller_id = str(controller.get("controller_id") or controller.get("id") or "").strip()
    if not controller_id:
        raise ValueError("controller identity is required")
    controller_name = str(controller.get("controller_name") or controller.get("name") or "Controller").strip()[:80]
    controller_url = str(controller.get("controller_url") or controller.get("url") or "").strip().rstrip("/")[:300]
    advertised_controller_url = str(
        controller.get("advertised_controller_url") or controller_url
    ).strip().rstrip("/")[:300]
    observed_controller_url = str(
        controller.get("observed_controller_url") or ""
    ).strip().rstrip("/")[:300]
    allowed_ips = controller.get("allowed_ips")
    if not isinstance(allowed_ips, list):
        allowed_ips = []

    controller_protocol = max(1, _safe_int(controller.get("protocol_version"), 1))

    def apply(data):
        pairing = data.get("pairing") if isinstance(data.get("pairing"), dict) else {}
        now = _now()
        expected = pairing.get("code_hash") or ""
        if not expected or not hmac.compare_digest(expected, _hash_pairing_code(normalized_code)):
            raise ValueError("invalid pairing code")
        if float(pairing.get("expires_at") or 0) < now:
            raise ValueError("pairing code expired")

        used_at = float(pairing.get("used_at") or 0)
        used_by = str(pairing.get("used_by_controller_id") or "")
        retrying_same_controller = bool(
            used_at
            and used_by == controller_id
            and now - used_at <= PAIRING_RETRY_GRACE_SECONDS
        )
        if used_at and not retrying_same_controller:
            raise ValueError("pairing code already used")

        token = secrets.token_urlsafe(32)
        recovery_token = secrets.token_urlsafe(40)
        trusted = data.setdefault("trusted_controllers", {})
        existing = trusted.get(controller_id) if isinstance(trusted.get(controller_id), dict) else {}
        paired_at = float(existing.get("paired_at") or now)
        trusted[controller_id] = {
            **existing,
            "id": controller_id,
            "name": controller_name,
            "token": token,
            "recovery_token_hash": _hash_secret(recovery_token),
            "url": controller_url,
            "advertised_url": advertised_controller_url,
            "observed_url": observed_controller_url,
            "paired_at": paired_at,
            "last_seen": 0,
            "allowed_ips": [str(ip).strip() for ip in allowed_ips if str(ip).strip()][:20],
            "protocol_version": min(NODE_PROTOCOL_VERSION, controller_protocol),
            "last_pair_request_id": str(controller.get("request_id") or "")[:80],
        }
        pairing.update({
            "used_at": used_at or now,
            "used_by_controller_id": controller_id,
            "last_retry_at": now if retrying_same_controller else 0,
            "attempt_count": int(pairing.get("attempt_count") or 0) + 1,
        })
        data["pairing"] = pairing
        return {
            "worker_id": data["local_node_id"],
            "worker_name": data.get("local_node_name") or "HandBrake TSD Node",
            "token": token,
            "recovery_token": recovery_token,
            "controller_url": controller_url,
            "advertised_controller_url": advertised_controller_url,
            "observed_controller_url": observed_controller_url,
            "paired_at": paired_at,
            "protocol_version": NODE_PROTOCOL_VERSION,
            "capabilities": NODE_CAPABILITIES,
            "retry_recovered": retrying_same_controller,
        }

    return _mutate_state(apply)


def recover_pairing(controller: dict) -> dict:
    """Repair a paired controller session without a new pairing code."""
    controller_id = str(controller.get("controller_id") or controller.get("id") or "").strip()
    if not controller_id:
        raise ValueError("controller identity is required")

    def apply(data):
        trusted = data.setdefault("trusted_controllers", {})
        row = trusted.get(controller_id)
        if not isinstance(row, dict):
            raise ValueError("controller is not paired")

        supplied_recovery = str(controller.get("recovery_token") or "").strip()
        supplied_session = str(controller.get("session_token") or "").strip()
        expected_recovery = str(row.get("recovery_token_hash") or "")
        recovery_ok = bool(expected_recovery and supplied_recovery and hmac.compare_digest(expected_recovery, _hash_secret(supplied_recovery)))
        session_ok = bool(supplied_session and hmac.compare_digest(str(row.get("token") or ""), supplied_session))
        if not recovery_ok and not session_ok:
            raise ValueError("pair recovery credential rejected")

        new_token = secrets.token_urlsafe(32)
        new_recovery = supplied_recovery if recovery_ok else secrets.token_urlsafe(40)
        now = _now()
        controller_url = str(controller.get("controller_url") or row.get("url") or "").strip().rstrip("/")[:300]
        advertised_controller_url = str(
            controller.get("advertised_controller_url")
            or row.get("advertised_url")
            or controller_url
        ).strip().rstrip("/")[:300]
        observed_controller_url = str(
            controller.get("observed_controller_url")
            or row.get("observed_url")
            or ""
        ).strip().rstrip("/")[:300]
        row.update({
            "token": new_token,
            "recovery_token_hash": _hash_secret(new_recovery),
            "url": controller_url,
            "advertised_url": advertised_controller_url,
            "observed_url": observed_controller_url,
            "last_seen": now,
            "recovered_at": now,
            "protocol_version": min(NODE_PROTOCOL_VERSION, max(1, _safe_int(controller.get("protocol_version"), row.get("protocol_version") or 1))),
        })
        trusted[controller_id] = row
        return {
            "worker_id": data.get("local_node_id"),
            "worker_name": data.get("local_node_name") or "HandBrake TSD Node",
            "token": new_token,
            "recovery_token": new_recovery,
            "controller_url": controller_url,
            "advertised_controller_url": advertised_controller_url,
            "observed_controller_url": observed_controller_url,
            "recovered_at": now,
            "protocol_version": NODE_PROTOCOL_VERSION,
            "capabilities": list(NODE_CAPABILITIES),
        }

    return _mutate_state(apply)


def enable_pair_recovery(controller_id: str) -> str:
    controller_id = str(controller_id or "")

    def apply(data):
        trusted = data.setdefault("trusted_controllers", {})
        row = trusted.get(controller_id)
        if not isinstance(row, dict):
            raise ValueError("controller is not paired")
        recovery_token = secrets.token_urlsafe(40)
        row["recovery_token_hash"] = _hash_secret(recovery_token)
        row["recovery_enabled_at"] = _now()
        trusted[controller_id] = row
        return recovery_token

    return _mutate_state(apply)


def public_node(row: dict) -> dict:
    row = row if isinstance(row, dict) else {}
    last_heartbeat = float(row.get("last_heartbeat") or 0)
    now = _now()
    age = max(0.0, now - last_heartbeat) if last_heartbeat else None
    allowed_age = heartbeat_allowed_age(row)
    online = bool(last_heartbeat) and bool(row.get("online")) and (age is not None and age <= allowed_age)
    status = str(row.get("status") or ("online" if online else "offline")).strip().lower()
    if online and status == "error" and not row.get("last_error"):
        status = "idle"
    heartbeat_misses = int(row.get("heartbeat_misses") or 0)
    running_work = node_has_running_work(row)
    if online and heartbeat_misses > 0:
        status = "reconnecting" if running_work else "stale"
    elif online and age is not None and age > HEARTBEAT_WARN_SECONDS:
        status = "reconnecting" if running_work else "stale"
    if not online and not last_heartbeat:
        status = "paired"
    elif not online:
        status = "offline"
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Worker",
        "url": row.get("url") or "",
        "role": row.get("role") or "worker",
        "online": online,
        "status": status,
        "connection_state": status,
        "heartbeat_misses": heartbeat_misses,
        "last_heartbeat_age_seconds": round(age, 1) if age is not None else None,
        "heartbeat_grace_seconds": allowed_age,
        "running_work": running_work,
        "summary": row.get("summary") if isinstance(row.get("summary"), dict) else {},
        "last_heartbeat": last_heartbeat,
        "last_error": row.get("last_error") or "",
        "last_job_error": row.get("last_job_error") or "",
        "path_mappings": row.get("path_mappings") if isinstance(row.get("path_mappings"), list) else [],
        "transfer_mode": normalize_transfer_mode(row.get("transfer_mode")),
        "controller_url": row.get("controller_url") or "",
        "remote_temp_dir": row.get("remote_temp_dir") or "",
        "hardware_transcode_concurrency": normalize_hardware_transcode_concurrency(
            row.get("hardware_transcode_concurrency"),
            1,
        ),
        "worker_encoding_policy": (
            row.get("worker_encoding_policy")
            if isinstance(row.get("worker_encoding_policy"), dict)
            else {}
        ),
        "worker_release": row.get("worker_release") or "",
        "worker_mode": row.get("worker_mode") or "full",
        "requires_remote_transfer": bool(row.get("requires_remote_transfer")),
        "paired_at": row.get("paired_at") or 0,
        "paired_controllers": row.get("paired_controllers") if isinstance(row.get("paired_controllers"), list) else [],
        "jobs": row.get("jobs") if isinstance(row.get("jobs"), list) else [],
        "prediction_profile": row.get("prediction_profile") if isinstance(row.get("prediction_profile"), dict) else {},
        "protocol_version": max(1, _safe_int(row.get("protocol_version"), 1)),
        "capabilities": row.get("capabilities") if isinstance(row.get("capabilities"), list) else [],
        "last_success_at": row.get("last_success_at") or 0,
        "consecutive_failures": _safe_int(row.get("consecutive_failures"), heartbeat_misses),
    }


def public_trusted_controller(row: dict) -> dict:
    row = row if isinstance(row, dict) else {}
    last_seen = float(row.get("last_seen") or 0)
    online = bool(last_seen and (_now() - last_seen <= HEARTBEAT_STALE_SECONDS))
    return {
        "id": row.get("id") or "",
        "name": row.get("name") or "Controller",
        "url": row.get("url") or "",
        "advertised_url": row.get("advertised_url") or "",
        "observed_url": row.get("observed_url") or "",
        "role": "controller",
        "online": online,
        "status": "online" if online else "paired",
        "paired_at": row.get("paired_at") or 0,
        "last_seen": last_seen,
        "allowed_ips": row.get("allowed_ips") if isinstance(row.get("allowed_ips"), list) else [],
        "protocol_version": max(1, _safe_int(row.get("protocol_version"), 1)),
    }


def list_trusted_controllers_public() -> list[dict]:
    data = _load_state()
    controllers = data.get("trusted_controllers") if isinstance(data.get("trusted_controllers"), dict) else {}
    return [public_trusted_controller(row) for row in controllers.values() if isinstance(row, dict)]


def local_node_overview() -> dict:
    data = _load_state()
    workers = [public_node(row) for row in (data.get("nodes") or {}).values() if isinstance(row, dict)]
    controllers = list_trusted_controllers_public()
    is_controller = bool(workers)
    is_worker = bool(controllers)
    if is_controller and is_worker:
        role = "controller_worker"
        role_label = "Master / Controller + Worker"
    elif is_controller:
        role = "controller"
        role_label = "Master / Controller"
    elif is_worker:
        role = "worker"
        role_label = "Worker"
    else:
        role = "standalone"
        role_label = "Standalone"
    return {
        "id": data.get("local_node_id"),
        "name": data.get("local_node_name") or "HandBrake TSD Node",
        "role": role,
        "role_label": role_label,
        "paired_worker_count": len(workers),
        "paired_controller_count": len(controllers),
        "paired_workers": workers,
        "paired_controllers": controllers,
    }


def list_nodes_public() -> list[dict]:
    data = _load_state()
    return [public_node(row) for row in (data.get("nodes") or {}).values()]


def list_nodes_private() -> list[dict]:
    data = _load_state()
    return [row for row in (data.get("nodes") or {}).values() if isinstance(row, dict)]


def get_node_private(node_id: str) -> dict | None:
    data = _load_state()
    row = (data.get("nodes") or {}).get(str(node_id or ""))
    return row if isinstance(row, dict) else None


def save_node(row: dict) -> dict:
    node_id = str(row.get("id") or "").strip()
    if not node_id:
        raise ValueError("missing node id")

    def apply(data):
        nodes = data.setdefault("nodes", {})
        existing = nodes.get(node_id) if isinstance(nodes.get(node_id), dict) else {}
        merged = {**existing, **row, "id": node_id}
        nodes[node_id] = merged
        return merged

    return _mutate_state(apply)


def delete_node(node_id: str) -> bool:
    node_id = str(node_id or "")

    def apply(data):
        nodes = data.setdefault("nodes", {})
        existed = node_id in nodes
        nodes.pop(node_id, None)
        return existed

    return _mutate_state(apply)


def delete_nodes_by_url(url: str, *, keep_id: str = "") -> int:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return 0
    def apply(data):
        nodes = data.setdefault("nodes", {})
        removed = 0
        for node_id, row in list(nodes.items()):
            if str(node_id) == str(keep_id or ""):
                continue
            if isinstance(row, dict) and str(row.get("url") or "").strip().rstrip("/") == value:
                nodes.pop(node_id, None)
                removed += 1
        return removed

    return _mutate_state(apply)


def trusted_controller(controller_id: str) -> dict | None:
    data = _load_state()
    row = (data.get("trusted_controllers") or {}).get(str(controller_id or ""))
    return row if isinstance(row, dict) else None


def trusted_controller_by_url(url: str) -> dict | None:
    wanted = str(url or "").strip().rstrip("/")
    if not wanted:
        return None
    data = _load_state()
    controllers = data.get("trusted_controllers") if isinstance(data.get("trusted_controllers"), dict) else {}
    for row in controllers.values():
        if isinstance(row, dict) and str(row.get("url") or "").strip().rstrip("/") == wanted:
            return row
    return None


def update_trusted_controller(controller_id: str, updates: dict) -> None:
    controller_id = str(controller_id or "")

    def apply(data):
        trusted = data.setdefault("trusted_controllers", {})
        row = trusted.get(controller_id)
        if not isinstance(row, dict):
            return
        row.update(updates)
        trusted[controller_id] = row

    _mutate_state(apply)


def delete_trusted_controller(controller_id: str) -> None:
    _mutate_state(lambda data: data.setdefault("trusted_controllers", {}).pop(str(controller_id or ""), None))


def normalize_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("worker URL must start with http:// or https://")
    return value


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
    timeout: int = 8,
    retries: int = 0,
) -> dict:
    body_bytes = b""
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=body_bytes if body is not None else None,
        method=method,
        headers={
            "accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
            **(headers or {}),
        },
    )
    payload = {}
    for attempt in range(max(0, int(retries)) + 1):
        try:
            with urlopen(req, timeout=timeout) as res:
                payload = json.loads(res.read().decode("utf-8", errors="replace"))
            break
        except HTTPError as e:
            try:
                error_payload = json.loads(e.read().decode("utf-8", errors="replace"))
            except Exception:
                error_payload = {"error": str(e)}
            raise RuntimeError(error_payload.get("error") or str(e))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            if attempt >= max(0, int(retries)):
                reason = getattr(e, "reason", e)
                raise RuntimeError(f"node request failed: {reason}")
            time.sleep(0.25 * (attempt + 1))
    return payload if isinstance(payload, dict) else {}


def pair_worker(
    worker_url: str,
    code: str,
    *,
    name: str = "",
    path_mappings: list | None = None,
    transfer_mode: str = "local",
    controller_url: str = "",
    remote_temp_dir: str = "",
    hardware_transcode_concurrency: int = 1,
) -> dict:
    url = normalize_url(worker_url)
    local = local_node_info()
    try:
        discovery = _request_json(f"{url}/api/node/discovery", timeout=5, retries=1)
    except RuntimeError:
        # Protocol v1 workers predate discovery and remain pairable.
        discovery = {"protocol_version": 1, "capabilities": []}
    request_id = uuid.uuid4().hex
    raw_code = str(code or "").strip()
    negotiated_protocol = max(1, _safe_int(discovery.get("protocol_version"), 1))
    payload = {
        # Legacy v1 codes were case-sensitive URL-safe tokens. v2 uses the
        # upper-case human format shown by discovery.
        "code": raw_code.upper() if negotiated_protocol >= 2 else raw_code,
        "controller_id": local["id"],
        "controller_name": local["name"],
        "controller_url": str(controller_url or "").strip().rstrip("/"),
        "protocol_version": NODE_PROTOCOL_VERSION,
        "capabilities": list(NODE_CAPABILITIES),
        "request_id": request_id,
    }
    # v2 pairing is idempotent for this controller during a short recovery
    # window, so a lost response can safely be retried.
    data = _request_json(f"{url}/api/node/pair/accept", method="POST", body=payload, timeout=10, retries=1)
    token = str(data.get("token") or "")
    recovery_token = str(data.get("recovery_token") or "")
    worker_id = str(data.get("worker_id") or data.get("id") or "").strip()
    if not token or not worker_id:
        raise RuntimeError("pairing response missing worker token")

    stored_controller_url = str(data.get("controller_url") or controller_url or "").strip().rstrip("/")
    requires_remote_transfer = bool(data.get("requires_remote_transfer") or discovery.get("requires_remote_transfer"))
    selected_transfer_mode = "remote" if requires_remote_transfer else normalize_transfer_mode(transfer_mode)
    worker_mode = str(data.get("worker_mode") or discovery.get("worker_mode") or "full").strip().lower()
    row = {
        "id": worker_id,
        "name": str(name or data.get("worker_name") or "Worker")[:80],
        "url": url,
        "role": "worker",
        "token": token,
        "recovery_token": recovery_token,
        "paired_at": _now(),
        "last_heartbeat": 0,
        "heartbeat_misses": 0,
        "last_failed_at": 0,
        "online": False,
        "status": "paired",
        "summary": {},
        "last_error": "",
        "path_mappings": [] if requires_remote_transfer else normalize_path_mappings(path_mappings or []),
        "transfer_mode": selected_transfer_mode,
        "controller_url": stored_controller_url,
        "remote_temp_dir": str(remote_temp_dir or "").strip()[:500],
        "hardware_transcode_concurrency": normalize_hardware_transcode_concurrency(
            hardware_transcode_concurrency,
            1,
        ),
        "worker_mode": worker_mode,
        "requires_remote_transfer": requires_remote_transfer,
        "protocol_version": max(1, _safe_int(data.get("protocol_version"), discovery.get("protocol_version") or 1)),
        "capabilities": data.get("capabilities") if isinstance(data.get("capabilities"), list) else (
            discovery.get("capabilities") if isinstance(discovery.get("capabilities"), list) else []
        ),
        "pair_request_id": request_id,
        "pair_retry_recovered": bool(data.get("retry_recovered")),
    }
    delete_nodes_by_url(url, keep_id=worker_id)
    save_node(row)
    return public_node(row)


def recover_worker_session(row: dict, *, controller_url: str = "") -> dict:
    worker_url = normalize_url(row.get("url") or "")
    local = local_node_info()
    payload = {
        "controller_id": local["id"],
        "controller_name": local["name"],
        "controller_url": str(controller_url or row.get("controller_url") or "").strip().rstrip("/"),
        "recovery_token": str(row.get("recovery_token") or ""),
        "session_token": str(row.get("token") or ""),
        "protocol_version": NODE_PROTOCOL_VERSION,
    }
    data = _request_json(f"{worker_url}/api/node/pair/recover", method="POST", body=payload, timeout=12)
    token = str(data.get("token") or "").strip()
    recovery_token = str(data.get("recovery_token") or row.get("recovery_token") or "").strip()
    if not token or not recovery_token:
        raise RuntimeError("pair recovery response was incomplete")
    updated = {
        **row,
        "token": token,
        "recovery_token": recovery_token,
        "controller_url": str(data.get("controller_url") or payload["controller_url"] or "").strip().rstrip("/"),
        "last_error": "",
        "heartbeat_misses": 0,
        "recovered_at": _now(),
        "status": "reconnecting",
        "protocol_version": max(1, _safe_int(data.get("protocol_version"), row.get("protocol_version") or 1)),
        "capabilities": data.get("capabilities") if isinstance(data.get("capabilities"), list) else row.get("capabilities", []),
    }
    return save_node(updated)


def normalize_path_mappings(rows) -> list[dict]:
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        controller = str(row.get("controller") or row.get("controller_prefix") or "").strip()
        worker = str(row.get("worker") or row.get("worker_prefix") or "").strip()
        if not controller or not worker:
            continue
        out.append({
            "controller": controller.rstrip("/\\"),
            "worker": worker.rstrip("/\\"),
        })
        if len(out) >= 50:
            break
    return out


def translate_path(path: str, mappings: list[dict]) -> str | None:
    value = str(path or "").strip()
    if not value:
        return None
    best = None
    for row in normalize_path_mappings(mappings):
        controller = row["controller"]
        key = controller.lower()
        value_l = value.lower()
        if value_l == key or value_l.startswith(key + "/") or value_l.startswith(key + "\\"):
            if best is None or len(controller) > len(best["controller"]):
                best = row
    if not best:
        return None
    rel = value[len(best["controller"]):].lstrip("/\\")
    sep = "\\" if "\\" in best["worker"] else "/"
    return best["worker"] + (sep + rel.replace("\\", sep).replace("/", sep) if rel else "")


def _empty_transfers() -> dict:
    return {"transfers": {}, "updated_at": 0}


def _load_transfers() -> dict:
    with TRANSFER_LOCK:
        try:
            with open(NODE_TRANSFER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = _empty_transfers()
            _save_transfers(data)
            return data
        except Exception:
            try:
                with open(NODE_TRANSFER_FILE + ".bak", "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = _empty_transfers()
                _save_transfers(data)
                return data
    if not isinstance(data, dict):
        data = _empty_transfers()
    data.setdefault("transfers", {})
    data.setdefault("updated_at", 0)
    return data


def _save_transfers(data: dict) -> None:
    with TRANSFER_LOCK:
        data["updated_at"] = _now()
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = NODE_TRANSFER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, NODE_TRANSFER_FILE)
        shutil.copy2(NODE_TRANSFER_FILE, NODE_TRANSFER_FILE + ".bak")


def create_transfer_grant(src: str, worker_node_id: str, *, source_size: int = 0, ttl_seconds: int = TRANSFER_TTL_SECONDS) -> dict:
    data = _load_transfers()
    transfers = data.setdefault("transfers", {})
    now = _now()
    transfer_id = uuid.uuid4().hex
    download_token = secrets.token_urlsafe(32)
    upload_token = secrets.token_urlsafe(32)
    expires_at = now + max(300, min(72 * 60 * 60, int(ttl_seconds or TRANSFER_TTL_SECONDS)))
    row = {
        "id": transfer_id,
        "src": str(src or ""),
        "source_basename": os.path.basename(str(src or "")) or "source.mkv",
        "source_size": int(source_size or 0),
        "worker_node_id": str(worker_node_id or ""),
        "download_token_hash": _hash_secret(download_token),
        "upload_token_hash": _hash_secret(upload_token),
        "created_at": now,
        "expires_at": expires_at,
        "download_used_at": 0,
        "upload_used_at": 0,
        "completed_at": 0,
        "status": "created",
        "error": "",
        "out_path": "",
        "out_bytes": 0,
        "saved_bytes": 0,
        "source_deleted": False,
    }
    transfers[transfer_id] = row
    _save_transfers(data)
    return {**row, "download_token": download_token, "upload_token": upload_token}


def get_transfer(transfer_id: str) -> dict | None:
    data = _load_transfers()
    row = (data.get("transfers") or {}).get(str(transfer_id or ""))
    return row if isinstance(row, dict) else None


def save_transfer(row: dict) -> dict:
    with TRANSFER_LOCK:
        data = _load_transfers()
        transfer_id = str(row.get("id") or "").strip()
        if not transfer_id:
            raise ValueError("missing transfer id")
        transfers = data.setdefault("transfers", {})
        existing = transfers.get(transfer_id) if isinstance(transfers.get(transfer_id), dict) else {}
        merged = {**existing, **row, "id": transfer_id}
        transfers[transfer_id] = merged
        _save_transfers(data)
        return merged


def renew_transfer_upload_grant(transfer_id: str, worker_node_id: str, *, ttl_seconds: int = TRANSFER_TTL_SECONDS) -> dict:
    with TRANSFER_LOCK:
        data = _load_transfers()
        transfers = data.setdefault("transfers", {})
        row = transfers.get(str(transfer_id or ""))
        if not isinstance(row, dict):
            raise ValueError("transfer not found")
        if str(row.get("worker_node_id") or "") != str(worker_node_id or ""):
            raise ValueError("transfer belongs to a different worker")
        if row.get("completed_at") or row.get("status") == "complete":
            return {
                "id": row.get("id"),
                "complete": True,
                "out_path": row.get("out_path") or "",
                "out_bytes": int(row.get("out_bytes") or 0),
                "saved_bytes": int(row.get("saved_bytes") or 0),
                "source_deleted": bool(row.get("source_deleted")),
            }

        token = secrets.token_urlsafe(32)
        now = _now()
        row.update({
            "upload_token_hash": _hash_secret(token),
            "upload_used_at": 0,
            "expires_at": now + max(300, min(72 * 60 * 60, int(ttl_seconds or TRANSFER_TTL_SECONDS))),
            "status": "waiting_for_upload",
            "error": "",
            "renewed_at": now,
        })
        transfers[str(transfer_id)] = row
        _save_transfers(data)
        return {**row, "upload_token": token, "complete": False}


def transfer_token_matches(row: dict, kind: str, token: str, *, require_unused: bool = True) -> bool:
    row = row if isinstance(row, dict) else {}
    kind = str(kind or "").strip().lower()
    if kind not in {"download", "upload"}:
        return False
    if float(row.get("expires_at") or 0) < _now():
        return False
    if require_unused and row.get(f"{kind}_used_at"):
        return False
    expected = str(row.get(f"{kind}_token_hash") or "")
    if not expected:
        return False
    return hmac.compare_digest(expected, _hash_secret(token))


def hmac_headers(method: str, path: str, body_bytes: bytes, *, node_id: str, token: str, timestamp: str | None = None) -> dict:
    ts = str(timestamp or int(_now()))
    message = b"\n".join([
        method.upper().encode("utf-8"),
        path.encode("utf-8"),
        ts.encode("utf-8"),
        body_bytes or b"",
    ])
    sig = hmac.new(str(token).encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "X-Node-Id": str(node_id),
        "X-Node-Timestamp": ts,
        "X-Node-Signature": sig,
    }


def verify_hmac(method: str, path: str, body_bytes: bytes, *, node_id: str, token: str, timestamp: str, signature: str, max_skew: int = 15 * 60) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(_now()) - ts) > max_skew:
        return False
    expected = hmac_headers(
        method,
        path,
        body_bytes,
        node_id=node_id,
        token=token,
        timestamp=str(ts),
    ).get("X-Node-Signature") or ""
    return hmac.compare_digest(expected, str(signature or ""))


def signed_json_request(node: dict, api_path: str, *, method: str = "GET", body: dict | None = None, timeout: int = 8) -> dict:
    # Worker-side trusted controller rows retain both the address advertised
    # by the browser and the source route observed on authenticated requests.
    # The observed route is the one known to be reachable from this worker.
    url = str(node.get("observed_url") or node.get("url") or "").rstrip("/") + api_path
    body_bytes = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = hmac_headers(
        method,
        api_path,
        body_bytes,
        node_id=local_node_info()["id"],
        token=str(node.get("token") or ""),
    )
    return _request_json(url, method=method, body=body, headers=headers, timeout=timeout)
