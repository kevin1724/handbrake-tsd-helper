from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import DATA_DIR


NODE_LINK_FILE = os.path.join(DATA_DIR.rstrip("/"), "linked_nodes.json")
NODE_TRANSFER_FILE = os.path.join(DATA_DIR.rstrip("/"), "node_transfers.json")
PAIRING_TTL_SECONDS = 15 * 60
HEARTBEAT_STALE_SECONDS = 90
TRANSFER_TTL_SECONDS = 6 * 60 * 60


def _now() -> float:
    return time.time()


def _empty_state() -> dict:
    return {
        "local_node_id": uuid.uuid4().hex,
        "local_node_name": "HandBrake TSD Node",
        "pairing": {},
        "trusted_controllers": {},
        "nodes": {},
        "updated_at": 0,
    }


def _load_state() -> dict:
    try:
        with open(NODE_LINK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = _empty_state()
        _save_state(data)
        return data
    except Exception:
        data = _empty_state()
        _save_state(data)
        return data

    if not isinstance(data, dict):
        data = _empty_state()

    data.setdefault("local_node_id", uuid.uuid4().hex)
    data.setdefault("local_node_name", "HandBrake TSD Node")
    data.setdefault("pairing", {})
    data.setdefault("trusted_controllers", {})
    data.setdefault("nodes", {})
    data.setdefault("updated_at", 0)
    return data


def _save_state(data: dict) -> None:
    data["updated_at"] = _now()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(NODE_LINK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def local_node_info() -> dict:
    data = _load_state()
    return {
        "id": data.get("local_node_id"),
        "name": data.get("local_node_name") or "HandBrake TSD Node",
    }


def set_local_node_name(name: str) -> dict:
    data = _load_state()
    value = str(name or "").strip()[:80] or "HandBrake TSD Node"
    data["local_node_name"] = value
    _save_state(data)
    return local_node_info()


def _hash_pairing_code(code: str) -> str:
    return hashlib.sha256(str(code or "").encode("utf-8", errors="ignore")).hexdigest()


def _hash_secret(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def normalize_transfer_mode(value: str) -> str:
    mode = str(value or "local").strip().lower()
    if mode in {"remote", "remote_transfer", "transfer"}:
        return "remote"
    return "local"


def create_pairing_code(ttl_seconds: int = PAIRING_TTL_SECONDS) -> dict:
    data = _load_state()
    code = secrets.token_urlsafe(10)
    expires_at = _now() + max(60, min(3600, int(ttl_seconds or PAIRING_TTL_SECONDS)))
    data["pairing"] = {
        "code_hash": _hash_pairing_code(code),
        "expires_at": expires_at,
        "created_at": _now(),
        "used_at": 0,
    }
    _save_state(data)
    return {"code": code, "expires_at": expires_at}


def accept_pairing(code: str, controller: dict) -> dict:
    data = _load_state()
    pairing = data.get("pairing") if isinstance(data.get("pairing"), dict) else {}
    now = _now()
    expected = pairing.get("code_hash") or ""
    if not expected or not hmac.compare_digest(expected, _hash_pairing_code(code)):
        raise ValueError("invalid pairing code")
    if float(pairing.get("expires_at") or 0) < now:
        raise ValueError("pairing code expired")
    if pairing.get("used_at"):
        raise ValueError("pairing code already used")

    controller_id = str(controller.get("controller_id") or controller.get("id") or "").strip() or uuid.uuid4().hex
    controller_name = str(controller.get("controller_name") or controller.get("name") or "Controller").strip()[:80]
    allowed_ips = controller.get("allowed_ips")
    if not isinstance(allowed_ips, list):
        allowed_ips = []

    token = secrets.token_urlsafe(32)
    trusted = data.setdefault("trusted_controllers", {})
    trusted[controller_id] = {
        "id": controller_id,
        "name": controller_name,
        "token": token,
        "paired_at": now,
        "last_seen": 0,
        "allowed_ips": [str(ip).strip() for ip in allowed_ips if str(ip).strip()][:20],
    }
    pairing["used_at"] = now
    data["pairing"] = pairing
    _save_state(data)

    return {
        "worker_id": data["local_node_id"],
        "worker_name": data.get("local_node_name") or "HandBrake TSD Node",
        "token": token,
        "paired_at": now,
    }


def public_node(row: dict) -> dict:
    row = row if isinstance(row, dict) else {}
    last_heartbeat = float(row.get("last_heartbeat") or 0)
    online = bool(row.get("online")) and (_now() - last_heartbeat <= HEARTBEAT_STALE_SECONDS)
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Worker",
        "url": row.get("url") or "",
        "role": row.get("role") or "worker",
        "online": online,
        "status": row.get("status") or ("online" if online else "offline"),
        "summary": row.get("summary") if isinstance(row.get("summary"), dict) else {},
        "last_heartbeat": last_heartbeat,
        "last_error": row.get("last_error") or "",
        "path_mappings": row.get("path_mappings") if isinstance(row.get("path_mappings"), list) else [],
        "transfer_mode": normalize_transfer_mode(row.get("transfer_mode")),
        "controller_url": row.get("controller_url") or "",
        "paired_at": row.get("paired_at") or 0,
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
    data = _load_state()
    node_id = str(row.get("id") or "").strip()
    if not node_id:
        raise ValueError("missing node id")
    nodes = data.setdefault("nodes", {})
    existing = nodes.get(node_id) if isinstance(nodes.get(node_id), dict) else {}
    merged = {**existing, **row, "id": node_id}
    nodes[node_id] = merged
    _save_state(data)
    return merged


def delete_node(node_id: str) -> bool:
    data = _load_state()
    nodes = data.setdefault("nodes", {})
    existed = str(node_id or "") in nodes
    nodes.pop(str(node_id or ""), None)
    _save_state(data)
    return existed


def trusted_controller(controller_id: str) -> dict | None:
    data = _load_state()
    row = (data.get("trusted_controllers") or {}).get(str(controller_id or ""))
    return row if isinstance(row, dict) else None


def update_trusted_controller(controller_id: str, updates: dict) -> None:
    data = _load_state()
    trusted = data.setdefault("trusted_controllers", {})
    row = trusted.get(str(controller_id or ""))
    if not isinstance(row, dict):
        return
    row.update(updates)
    trusted[str(controller_id)] = row
    _save_state(data)


def delete_trusted_controller(controller_id: str) -> None:
    data = _load_state()
    trusted = data.setdefault("trusted_controllers", {})
    trusted.pop(str(controller_id or ""), None)
    _save_state(data)


def normalize_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("worker URL must start with http:// or https://")
    return value


def _request_json(url: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: int = 8) -> dict:
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
    try:
        with urlopen(req, timeout=timeout) as res:
            payload = json.loads(res.read().decode("utf-8", errors="replace"))
    except HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            payload = {"error": str(e)}
        raise RuntimeError(payload.get("error") or str(e))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise RuntimeError(str(e))
    return payload if isinstance(payload, dict) else {}


def pair_worker(worker_url: str, code: str, *, name: str = "", path_mappings: list | None = None, transfer_mode: str = "local", controller_url: str = "") -> dict:
    url = normalize_url(worker_url)
    local = local_node_info()
    payload = {
        "code": str(code or "").strip(),
        "controller_id": local["id"],
        "controller_name": local["name"],
    }
    data = _request_json(f"{url}/api/node/pair/accept", method="POST", body=payload, timeout=10)
    token = str(data.get("token") or "")
    worker_id = str(data.get("worker_id") or data.get("id") or "").strip()
    if not token or not worker_id:
        raise RuntimeError("pairing response missing worker token")

    row = {
        "id": worker_id,
        "name": str(name or data.get("worker_name") or "Worker")[:80],
        "url": url,
        "role": "worker",
        "token": token,
        "paired_at": _now(),
        "last_heartbeat": 0,
        "online": False,
        "status": "paired",
        "summary": {},
        "last_error": "",
        "path_mappings": normalize_path_mappings(path_mappings or []),
        "transfer_mode": normalize_transfer_mode(transfer_mode),
        "controller_url": str(controller_url or "").strip().rstrip("/"),
    }
    save_node(row)
    return public_node(row)


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
    try:
        with open(NODE_TRANSFER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = _empty_transfers()
        _save_transfers(data)
        return data
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
    data["updated_at"] = _now()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(NODE_TRANSFER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def create_transfer_grant(src: str, worker_node_id: str, *, source_size: int = 0, ttl_seconds: int = TRANSFER_TTL_SECONDS) -> dict:
    data = _load_transfers()
    transfers = data.setdefault("transfers", {})
    now = _now()
    transfer_id = uuid.uuid4().hex
    download_token = secrets.token_urlsafe(32)
    upload_token = secrets.token_urlsafe(32)
    expires_at = now + max(300, min(24 * 60 * 60, int(ttl_seconds or TRANSFER_TTL_SECONDS)))
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


def verify_hmac(method: str, path: str, body_bytes: bytes, *, node_id: str, token: str, timestamp: str, signature: str, max_skew: int = 300) -> bool:
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
    url = str(node.get("url") or "").rstrip("/") + api_path
    body_bytes = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = hmac_headers(
        method,
        api_path,
        body_bytes,
        node_id=local_node_info()["id"],
        token=str(node.get("token") or ""),
    )
    return _request_json(url, method=method, body=body, headers=headers, timeout=timeout)
