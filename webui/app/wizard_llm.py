"""On-demand local language model for the Size Wizard assistant."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading


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


def wizard_llm_status() -> dict:
    binary_ready = os.path.isfile(LLM_BIN) and os.access(LLM_BIN, os.X_OK)
    model_ready = os.path.isfile(LLM_MODEL)
    try:
        model_bytes = os.path.getsize(LLM_MODEL) if model_ready else 0
    except OSError:
        model_bytes = 0
    return {
        "enabled": bool(LLM_ENABLED),
        "ready": bool(LLM_ENABLED and binary_ready and model_ready),
        "binary_ready": binary_ready,
        "model_ready": model_ready,
        "model": "Qwen2.5 0.5B Instruct Q4_0",
        "model_bytes": model_bytes,
        "on_demand": True,
        "threads": LLM_THREADS,
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


def run_wizard_llm(question: str, plan: dict) -> dict:
    status = wizard_llm_status()
    if not status["ready"]:
        return {"ok": False, "error": "local model is not installed", "status": status}

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
