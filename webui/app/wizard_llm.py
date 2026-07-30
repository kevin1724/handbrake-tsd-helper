"""On-demand local language model for the Size Wizard assistant."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

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
