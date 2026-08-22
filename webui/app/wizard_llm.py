"""On-demand local language model for the Size Wizard assistant."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import DATA_DIR
from .settings import load_settings


LLM_BIN = os.environ.get("HB_WIZARD_LLM_BIN", "/usr/local/bin/llama-cli")
LLM_MODEL = os.environ.get(
    "HB_WIZARD_LLM_MODEL",
    "/models/qwen2.5-0.5b-instruct-q4_0.gguf",
)
LLM_ENABLED = os.environ.get("HB_WIZARD_LLM_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
LLM_TIMEOUT_SECONDS = max(15, min(180, int(os.environ.get("HB_WIZARD_LLM_TIMEOUT", "90"))))
LLM_THREADS = max(1, min(4, int(os.environ.get("HB_WIZARD_LLM_THREADS", "2"))))
_INFERENCE_LOCK = threading.Lock()
_EPISODE_AI_LOCK = threading.RLock()
EPISODE_AI_CACHE_FILE = os.path.join(DATA_DIR, "episode_scene_ai_cache.json")
EPISODE_AI_CACHE_LIMIT = 500
_OUTPUT_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "maxLength": 600},
            "updates": {
                "type": "object",
                "properties": {
                    "ai_goal": {"enum": ["balanced", "quality", "speed", "small", "archive"]},
                    "ai_hardware": {"enum": ["auto", "software", "qsv"]},
                    "ai_codec_preference": {"enum": ["auto", "h264", "h265", "av1"]},
                    "ai_risk": {"enum": ["safe", "smart", "explorer", "bold"]},
                    "resolution_mode": {"enum": ["auto", "keep", "720", "1080", "1440", "2160"]},
                    "target_size_value": {"type": "number"},
                    "target_size_unit": {"enum": ["MB", "GB"]},
                    "target_size_auto": {"type": "boolean"},
                    "ai_copy_audio": {"type": "boolean"},
                    "ai_audio_scope": {"enum": ["first", "all"]},
                    "ai_subtitle_scope": {"enum": ["none", "first", "all"]},
                },
                "additionalProperties": False,
            },
            "confidence": {"type": "string", "maxLength": 24},
        },
        "required": ["answer", "updates", "confidence"],
        "additionalProperties": False,
    },
    separators=(",", ":"),
)


def episode_scene_fingerprint(src_path: str) -> str:
    """Return a stable, content-version-aware identifier without exposing a path."""
    stat = os.stat(src_path)
    raw = f"{os.path.realpath(src_path)}\0{stat.st_size}\0{stat.st_mtime_ns}".encode(
        "utf-8", errors="surrogatepass"
    )
    return hashlib.sha256(raw).hexdigest()


def _episode_ai_fallback(enabled: bool, reason: str, *, fingerprint: str = "") -> dict:
    return {
        "enabled": bool(enabled),
        "attempted": False,
        "used": False,
        "cached": False,
        "fingerprint": fingerprint,
        "target_scale": 1.0,
        "summary": "",
        "scene_types": [],
        "profile": {},
        "reason": str(reason or "deterministic episode analysis used")[:240],
    }


def _load_episode_ai_cache() -> dict:
    try:
        with open(EPISODE_AI_CACHE_FILE, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}


def _save_episode_ai_cache(cache: dict) -> None:
    rows = sorted(
        ((key, value) for key, value in cache.items() if isinstance(value, dict)),
        key=lambda item: float(item[1].get("created_at") or 0.0),
        reverse=True,
    )[:EPISODE_AI_CACHE_LIMIT]
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="episode_scene_ai_", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(rows), handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, EPISODE_AI_CACHE_FILE)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _episode_sample_timestamps(duration_sec: float, count: int) -> list[float]:
    duration = max(1.0, float(duration_sec or 0.0))
    count = max(3, min(8, int(count or 4)))
    # Avoid title cards and end credits while covering the complete episode.
    start, end = duration * 0.12, duration * 0.88
    if count == 1:
        return [duration * 0.5]
    return [start + (end - start) * index / (count - 1) for index in range(count)]


def _sample_episode_frames(src_path: str, duration_sec: float, count: int) -> list[bytes]:
    frames = []
    for timestamp in _episode_sample_timestamps(duration_sec, count):
        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                src_path,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                "scale=768:-2:force_original_aspect_ratio=decrease,format=yuv420p",
                "-q:v",
                "5",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
            check=False,
        )
        frame = bytes(completed.stdout or b"")
        if completed.returncode == 0 and 1_000 <= len(frame) <= 750_000:
            frames.append(frame)
    if len(frames) < 3:
        raise RuntimeError("ffmpeg could not extract at least three representative episode frames")
    return frames


def _episode_scene_prompt(probe: dict) -> str:
    facts = {
        "width": int(probe.get("width") or 0),
        "height": int(probe.get("height") or 0),
        "fps": round(float(probe.get("fps") or 0.0), 3),
        "duration_seconds": round(float(probe.get("duration_sec") or 0.0), 2),
        "video_codec": str(probe.get("video_codec") or "unknown")[:30],
        "hdr": bool(probe.get("is_hdr")),
        "hdr_reason": str(probe.get("hdr_reason") or "")[:80],
    }
    return (
        "Analyze these representative stills only for video-compression characteristics. "
        "Do not identify people, infer the title, or retell the plot. Describe the visual mix across the samples. "
        "Return one JSON object with: summary (max 45 words), scene_types (max 6 short tags), "
        "complexity (low|medium|high), motion (low|medium|high), grain (clean|light|heavy), "
        "lighting (bright|mixed|dark), content_type (live_action|animation|screen|mixed), and "
        "quality_bias (-1, 0, or 1). quality_bias means a small bitrate adjustment only; deterministic "
        "HDR/color, resolution, audio, subtitle, and encoder safety rules remain authoritative. TECHNICAL_FACTS="
        + json.dumps(facts, separators=(",", ":"), ensure_ascii=True)
    )


def _extract_episode_scene_json(text: str) -> dict:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(raw)
    decoder = json.JSONDecoder()
    candidates.extend(raw[match.start() :] for match in re.finditer(r"\{", raw))
    for candidate in candidates:
        try:
            value, _end = decoder.raw_decode(candidate.strip())
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("complexity") and value.get("motion"):
            return value
    raise ValueError("vision provider did not return a valid scene profile")


def _sanitize_episode_scene_result(value: dict, *, provider: str, model: str, fingerprint: str) -> dict:
    def choice(key: str, allowed: set[str], default: str) -> str:
        candidate = str(value.get(key) or default).strip().lower()
        return candidate if candidate in allowed else default

    complexity = choice("complexity", {"low", "medium", "high"}, "medium")
    motion = choice("motion", {"low", "medium", "high"}, "medium")
    grain = choice("grain", {"clean", "light", "heavy"}, "light")
    lighting = choice("lighting", {"bright", "mixed", "dark"}, "mixed")
    content_type = choice(
        "content_type", {"live_action", "animation", "screen", "mixed"}, "mixed"
    )
    try:
        quality_bias = int(round(float(value.get("quality_bias") or 0)))
    except (TypeError, ValueError):
        quality_bias = 0
    quality_bias = max(-1, min(1, quality_bias))

    scale = 1.0
    scale += {"low": -0.05, "medium": 0.0, "high": 0.08}[complexity]
    scale += {"low": -0.02, "medium": 0.0, "high": 0.06}[motion]
    scale += {"clean": -0.02, "light": 0.0, "heavy": 0.08}[grain]
    scale += 0.04 if lighting == "dark" else 0.0
    scale += quality_bias * 0.03
    if content_type == "animation" and motion != "high" and grain == "clean":
        scale -= 0.03
    scale = round(max(0.90, min(1.22, scale)), 2)

    scene_types = []
    for item in value.get("scene_types") if isinstance(value.get("scene_types"), list) else []:
        tag = " ".join(str(item or "").split())[:32]
        if tag and tag.lower() not in {row.lower() for row in scene_types}:
            scene_types.append(tag)
        if len(scene_types) >= 6:
            break
    summary = " ".join(str(value.get("summary") or "").split())[:280]
    return {
        "enabled": True,
        "attempted": True,
        "used": True,
        "cached": False,
        "provider": provider,
        "model": model[:100],
        "fingerprint": fingerprint,
        "target_scale": scale,
        "summary": summary,
        "scene_types": scene_types,
        "profile": {
            "complexity": complexity,
            "motion": motion,
            "grain": grain,
            "lighting": lighting,
            "content_type": content_type,
            "quality_bias": quality_bias,
        },
        "reason": "representative frames analyzed independently for this episode",
    }


def analyze_episode_scenes(
    src_path: str,
    probe: dict,
    *,
    profile: dict | None = None,
    settings: dict | None = None,
) -> dict:
    """Optionally classify representative frames for one immutable Smart plan.

    Only bounded compression hints are returned. The caller keeps deterministic
    HDR/color, dimensions, track selection, and encoder compatibility in charge.
    """
    profile = profile if isinstance(profile, dict) else {}
    enabled = bool(profile.get("episode_ai_enabled", False))
    if not enabled:
        return _episode_ai_fallback(False, "beta per-episode scene analysis is disabled")
    try:
        fingerprint = episode_scene_fingerprint(src_path)
    except OSError as exc:
        return _episode_ai_fallback(True, f"episode fingerprint failed: {exc}")

    config = _provider_config(settings)
    provider = config.get("provider") or "local"
    if provider not in {"gemini", "openai"}:
        return _episode_ai_fallback(
            True,
            "select a configured OpenAI or Gemini cloud provider for beta scene analysis",
            fingerprint=fingerprint,
        )
    key_name = f"{provider}_key"
    model_name = str(config.get(f"{provider}_model") or "").strip()
    if not config.get(key_name):
        return _episode_ai_fallback(
            True, f"{provider} API key is not configured", fingerprint=fingerprint
        )

    with _EPISODE_AI_LOCK:
        cached = _load_episode_ai_cache().get(fingerprint)
    if isinstance(cached, dict) and isinstance(cached.get("result"), dict):
        result = dict(cached["result"])
        result["cached"] = True
        return result

    try:
        frame_count = max(3, min(8, int(profile.get("episode_ai_frame_count") or 4)))
        frames = _sample_episode_frames(src_path, float(probe.get("duration_sec") or 0.0), frame_count)
        prompt = _episode_scene_prompt(probe)
        if provider == "gemini":
            model = quote(model_name, safe="-._")
            request = Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": config[key_name]},
            )
            parts = [{"text": prompt}] + [
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(frame).decode("ascii"),
                    }
                }
                for frame in frames
            ]
            payload = _http_json(
                request,
                {
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 450},
                },
            )
            try:
                output_text = payload["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError("Gemini returned no scene-analysis text") from exc
        else:
            request = Request(
                "https://api.openai.com/v1/responses",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config[key_name]}",
                },
            )
            content = [{"type": "input_text", "text": prompt}] + [
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii"),
                    "detail": "low",
                }
                for frame in frames
            ]
            payload = _http_json(
                request,
                {
                    "model": model_name,
                    "instructions": (
                        "You are a bounded video-compression scene classifier. Return only the requested JSON."
                    ),
                    "input": [{"role": "user", "content": content}],
                    "max_output_tokens": 450,
                },
            )
            output_text = _openai_output_text(payload)
            if not output_text:
                raise RuntimeError("OpenAI returned no scene-analysis text")

        parsed = _extract_episode_scene_json(output_text)
        result = _sanitize_episode_scene_result(
            parsed, provider=provider, model=model_name, fingerprint=fingerprint
        )
        with _EPISODE_AI_LOCK:
            cache = _load_episode_ai_cache()
            cache[fingerprint] = {"created_at": time.time(), "result": result}
            _save_episode_ai_cache(cache)
        return result
    except Exception as exc:
        fallback = _episode_ai_fallback(True, f"scene analysis fallback: {exc}", fingerprint=fingerprint)
        fallback["attempted"] = True
        fallback["provider"] = provider
        fallback["model"] = model_name[:100]
        return fallback


def _provider_config(settings: dict | None = None) -> dict:
    settings = settings if isinstance(settings, dict) else load_settings()
    provider = str(settings.get("wizard_ai_provider") or "local").strip().lower()
    if provider not in {"off", "local", "gemini", "openai"}:
        provider = "local"
    gemini_key = str(os.environ.get("GEMINI_API_KEY") or settings.get("gemini_api_key") or "").strip()
    openai_key = str(os.environ.get("OPENAI_API_KEY") or settings.get("openai_api_key") or "").strip()
    return {
        "provider": provider,
        "gemini_key": gemini_key,
        "gemini_model": str(settings.get("gemini_model") or "gemini-3.6-flash").strip(),
        "openai_key": openai_key,
        "openai_model": str(settings.get("openai_model") or "gpt-5.6-luna").strip(),
    }


def wizard_llm_status(settings: dict | None = None) -> dict:
    config = _provider_config(settings)
    binary_ready = os.path.isfile(LLM_BIN) and os.access(LLM_BIN, os.X_OK)
    model_ready = os.path.isfile(LLM_MODEL)
    try:
        model_bytes = os.path.getsize(LLM_MODEL) if model_ready else 0
    except OSError:
        model_bytes = 0
    local_ready = bool(LLM_ENABLED and binary_ready and model_ready)
    provider = config["provider"]
    selected_ready = {
        "off": False,
        "local": local_ready,
        "gemini": bool(config["gemini_key"]),
        "openai": bool(config["openai_key"]),
    }[provider]
    selected_model = {
        "off": "Deterministic planner only",
        "local": "Qwen2.5 0.5B Instruct Q4_0",
        "gemini": config["gemini_model"],
        "openai": config["openai_model"],
    }[provider]
    return {
        "enabled": bool(LLM_ENABLED),
        "ready": selected_ready,
        "provider": provider,
        "binary_ready": binary_ready,
        "model_ready": model_ready,
        "model": selected_model,
        "model_bytes": model_bytes,
        "on_demand": True,
        "threads": LLM_THREADS,
        "providers": {
            "local": {"configured": local_ready, "model": "Qwen2.5 0.5B Instruct Q4_0"},
            "gemini": {"configured": bool(config["gemini_key"]), "model": config["gemini_model"]},
            "openai": {"configured": bool(config["openai_key"]), "model": config["openai_model"]},
        },
    }


def _compact_plan_context(plan: dict) -> dict:
    estimates = plan.get("estimates") or {}
    inputs = plan.get("inputs") or {}
    probe = plan.get("probe") or {}
    history = estimates.get("history_prediction") or {}
    return {
        "source": {
            "name": os.path.basename(str(plan.get("src") or "")),
            "width": probe.get("width"),
            "height": probe.get("height"),
            "duration_seconds": probe.get("duration_sec"),
            "size_bytes": probe.get("source_size_bytes"),
            "hdr": bool(probe.get("is_hdr")),
            "type": probe.get("source_type"),
        },
        "plan": {
            "goal": inputs.get("ai_goal"),
            "risk": inputs.get("ai_risk"),
            "target_mb": inputs.get("target_mb"),
            "codec": inputs.get("video_codec"),
            "encoder_family": inputs.get("encoder_family"),
            "encoder": estimates.get("encoder"),
            "resolution_mode": inputs.get("resolution_mode"),
            "output_resolution": estimates.get("output_resolution"),
            "quality": estimates.get("quality_label"),
            "bpp": estimates.get("bpp"),
            "eta_seconds": estimates.get("eta_seconds"),
            "audio_mode": inputs.get("audio_mode"),
            "audio_tracks": inputs.get("audio_tracks"),
            "subtitles": inputs.get("subtitle_mode"),
            "history_samples": history.get("sample_count") if history.get("available") else 0,
        },
        "decisions": list(estimates.get("ai_decisions") or [])[-4:],
        "warnings": list(estimates.get("ai_warnings") or [])[:3],
    }


def _extract_json(text: str) -> dict:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    candidates = [fenced.group(1)] if fenced else []
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict) and "answer" in value:
                return value
        except (TypeError, ValueError):
            continue

    decoder = json.JSONDecoder()
    found = []
    for match in re.finditer(r"\{", raw):
        try:
            value, _end = decoder.raw_decode(raw[match.start() :])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and "answer" in value:
            found.append(value)
    if found:
        return found[-1]
    raise ValueError("local model did not return valid JSON")


def _clean_answer(value) -> str:
    answer = " ".join(str(value or "").split()).strip()[:600]
    if answer and answer[-1] not in ".!?":
        last_stop = max(answer.rfind("."), answer.rfind("!"), answer.rfind("?"))
        if last_stop >= 80:
            answer = answer[: last_stop + 1]
        else:
            answer = answer.rstrip(" ,;:") + "."
    return answer


def _cloud_prompt(question: str, plan: dict) -> tuple[str, str]:
    system = (
        "You are the optional Size Wizard advisor for a HandBrake media encoder. "
        "Use only the supplied scan and plan facts. Explain tradeoffs in plain language in at most 80 words. "
        "The deterministic ByteSqueeze planner is authoritative; never invent media facts or raw commands. "
        "Keep all English and Spanish audio and subtitle tracks. Preserve surround sound by passthrough when possible, "
        "otherwise recommend E-AC3 5.1. You may propose only these update keys: ai_goal, ai_hardware, "
        "ai_codec_preference, ai_risk, resolution_mode, target_size_value, target_size_unit, target_size_auto, "
        "ai_copy_audio, ai_audio_scope, ai_subtitle_scope. Return only JSON with answer, updates, and confidence."
    )
    prompt = (
        "PLAN="
        + json.dumps(_compact_plan_context(plan), separators=(",", ":"), ensure_ascii=True)
        + "\nQUESTION="
        + str(question or "")[:500]
    )
    return system, prompt


def _http_json(request: Request, payload: dict) -> dict:
    try:
        with urlopen(request, data=json.dumps(payload).encode("utf-8"), timeout=35) as response:
            value = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"provider returned HTTP {exc.code}: {detail[:220]}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)[:240]) from exc
    if not isinstance(value, dict):
        raise RuntimeError("provider returned an invalid response")
    return value


def _openai_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if direct:
        return str(direct)
    parts = []
    for item in payload.get("output") if isinstance(payload.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") if isinstance(item.get("content"), list) else []:
            if isinstance(content, dict) and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts)


def _run_cloud_provider(provider: str, question: str, plan: dict, config: dict, status: dict) -> dict:
    system, prompt = _cloud_prompt(question, plan)
    if provider == "gemini":
        model = quote(config["gemini_model"], safe="-._")
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": config["gemini_key"]},
        )
        payload = _http_json(
            request,
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 500},
            },
        )
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini returned no text response") from exc
    else:
        request = Request(
            "https://api.openai.com/v1/responses",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config['openai_key']}",
            },
        )
        payload = _http_json(
            request,
            {
                "model": config["openai_model"],
                "instructions": system,
                "input": prompt,
                "max_output_tokens": 500,
            },
        )
        text = _openai_output_text(payload)
        if not text:
            raise RuntimeError("OpenAI returned no text response")

    parsed = _extract_json(text)
    answer = _clean_answer(parsed.get("answer"))
    if not answer:
        raise ValueError("provider returned an empty answer")
    return {
        "ok": True,
        "answer": answer,
        "updates": parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {},
        "confidence": str(parsed.get("confidence") or "model").strip()[:40],
        "status": status,
    }


def run_wizard_llm(question: str, plan: dict, settings: dict | None = None) -> dict:
    config = _provider_config(settings)
    status = wizard_llm_status(settings)
    provider = config["provider"]
    if not status["ready"]:
        message = {
            "off": "cloud advisor is disabled",
            "local": "local model is not installed",
            "gemini": "Gemini API key is not configured",
            "openai": "OpenAI API key is not configured",
        }[provider]
        return {"ok": False, "error": message, "status": status}

    if provider in {"gemini", "openai"}:
        try:
            return _run_cloud_provider(provider, question, plan, config, status)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "status": status}

    system = (
        "You are the local Size Wizard AI for a HandBrake media encoder. "
        "Use only the supplied plan facts. Explain tradeoffs clearly in at most 80 words. "
        "Never invent file details, benchmarks, or commands. The deterministic planner is authoritative. "
        "You may propose only these update keys: ai_goal, ai_hardware, ai_codec_preference, "
        "ai_risk, resolution_mode, target_size_value, target_size_unit, target_size_auto, "
        "ai_copy_audio, ai_audio_scope, ai_subtitle_scope. Use an empty updates object for questions. "
        "Return one JSON object with keys answer, updates, confidence."
    )
    prompt = (
        "PLAN="
        + json.dumps(_compact_plan_context(plan), separators=(",", ":"), ensure_ascii=True)
        + "\nQUESTION="
        + str(question or "")[:500]
    )
    command = [
        LLM_BIN,
        "-m",
        LLM_MODEL,
        "-p",
        prompt,
        "--system-prompt",
        system,
        "-n",
        "400",
        "-c",
        "1024",
        "-b",
        "128",
        "-t",
        str(LLM_THREADS),
        "--temp",
        "0.2",
        "--top-p",
        "0.9",
        "--json-schema",
        _OUTPUT_SCHEMA,
        "--no-display-prompt",
        "--conversation",
        "--single-turn",
        "--no-warmup",
        "--simple-io",
    ]

    if not _INFERENCE_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "local model is already answering another request", "status": status}
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=LLM_TIMEOUT_SECONDS,
            check=False,
            env=os.environ.copy(),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            return {
                "ok": False,
                "error": detail[-1][:240] if detail else "local model process failed",
                "status": status,
            }
        parsed = _extract_json(completed.stdout)
        answer = _clean_answer(parsed.get("answer"))
        if not answer:
            raise ValueError("local model returned an empty answer")
        return {
            "ok": True,
            "answer": answer,
            "updates": parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {},
            "confidence": str(parsed.get("confidence") or "model").strip()[:40],
            "status": status,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "local model timed out", "status": status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:240], "status": status}
    finally:
        _INFERENCE_LOCK.release()
