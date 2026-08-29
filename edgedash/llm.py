from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Callable

from edgedash.config import Config, load_config


class LLMError(Exception):
    """Raised when an LLM call fails, exhausts retries, or schema validation fails."""


# ── Rate Limiter State ──────────────────────────────────────────────
_last_call_time: float = 0.0
_call_history: deque[float] = deque(maxlen=30)


def _enforce_rate_limits(provider: str = "gemini") -> None:
    global _last_call_time
    now = time.monotonic()
    
    # Provider-aware minimum spacing
    if provider.lower() == "groq":
        min_gap = 1.5   # Groq supports 30 RPM
        max_rpm = 30
    elif provider.lower() == "ollama":
        min_gap = 0.0   # Local Ollama has no rate limit
        max_rpm = 1000
    else:
        min_gap = 4.0   # Gemini free tier supports 15 RPM
        max_rpm = 15

    elapsed = now - _last_call_time
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)

    # Rolling window cap
    if len(_call_history) >= max_rpm:
        oldest = _call_history[-max_rpm]
        window = time.monotonic() - oldest
        if window < 60.0:
            time.sleep(60.0 - window + 0.5)

    recorded = time.monotonic()
    _call_history.append(recorded)
    _last_call_time = recorded


# ── Provider Implementations ───────────────────────────────────────
PROVIDERS: dict[str, Callable[[str, str], str]] = {}


def register_provider(name: str) -> Callable[[Callable[[str, str], str]], Callable[[str, str], str]]:
    def decorator(fn: Callable[[str, str], str]) -> Callable[[str, str], str]:
        PROVIDERS[name.lower()] = fn
        return fn
    return decorator


@register_provider("gemini")
def _call_gemini(prompt: str, model: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError(
            "GEMINI_API_KEY is not set. Please add GEMINI_API_KEY to your .env file."
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return _send_request_with_backoff(
        req, lambda data: data["candidates"][0]["content"]["parts"][0]["text"], provider="gemini"
    )


@register_provider("ollama")
def _call_ollama(prompt: str, model: str) -> str:
    url = "http://localhost:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return _send_request_with_backoff(req, lambda data: data.get("response", ""), provider="ollama")


@register_provider("groq")
def _call_groq(prompt: str, model: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMError(
            "GROQ_API_KEY is not set. Please add GROQ_API_KEY to your .env file."
        )

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model or "openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "EdgeDash/1.0",
        },
    )
    return _send_request_with_backoff(
        req, lambda data: data["choices"][0]["message"]["content"], provider="groq"
    )


@register_provider("openrouter")
def _call_openrouter(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMError(
            "OPENROUTER_API_KEY is not set. Please add OPENROUTER_API_KEY to your .env file."
        )

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model or "meta-llama/llama-3.3-70b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    return _send_request_with_backoff(
        req, lambda data: data["choices"][0]["message"]["content"], provider="openrouter"
    )


def _send_request_with_backoff(
    req: urllib.request.Request,
    extract_fn: Callable[[dict[str, Any]], str],
    provider: str = "gemini",
) -> str:
    last_exc: Exception | None = None
    for attempt in range(4):
        _enforce_rate_limits(provider)
        try:
            with urllib.request.urlopen(req, timeout=30.0) as res:
                body = json.loads(res.read().decode("utf-8"))
                return extract_fn(body)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < 3:
                # Generous backoff for 429 quota refresh: 6s, 15s, 30s
                sleep_time = (attempt + 1) * 8.0
                time.sleep(sleep_time)
                continue
            raise LLMError(f"HTTP error {exc.code} calling LLM provider: {exc.reason}") from exc
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(2.0 ** (attempt + 1))
                continue
            raise LLMError(f"Error calling LLM provider: {exc}") from exc
    raise LLMError(f"LLM request failed after retries: {last_exc}") from last_exc


# ── Parsing & Validation ───────────────────────────────────────────
def _clean_json_text(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _validate_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Output must be a JSON object (dict)."
    for key, expected_type in schema.items():
        if key not in data:
            return False, f"Missing required key: '{key}'"
        if isinstance(expected_type, type) and not isinstance(data[key], expected_type):
            return False, f"Key '{key}' must be {expected_type.__name__}, got {type(data[key]).__name__}"
    return True, ""


# ── Public API ─────────────────────────────────────────────────────
def complete_json(
    prompt: str,
    schema: dict[str, Any],
    *,
    max_retries: int = 1,
    config: Config | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    provider_name = cfg.llm_provider.lower()
    provider_fn = PROVIDERS.get(provider_name)
    if not provider_fn:
        raise LLMError(f"Unknown LLM provider: '{cfg.llm_provider}'. Supported: {list(PROVIDERS.keys())}")

    current_prompt = prompt
    last_error = ""
    for attempt in range(max_retries + 1):
        raw_output = provider_fn(current_prompt, cfg.llm_model)
        cleaned = _clean_json_text(raw_output)
        try:
            parsed = json.loads(cleaned)
            is_valid, err_msg = _validate_schema(parsed, schema)
            if is_valid:
                return parsed
            last_error = err_msg
        except json.JSONDecodeError as exc:
            last_error = f"Invalid JSON syntax: {exc}"

        if attempt < max_retries:
            current_prompt = (
                f"{prompt}\n\n"
                f"CRITICAL FIX REQUIRED:\n"
                f"Your previous reply failed validation: {last_error}\n"
                f"Reply ONLY with pure valid JSON matching the schema. No markdown fences, no explanation."
            )

    raise LLMError(f"Failed to obtain valid JSON matching schema after {max_retries + 1} attempts: {last_error}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        cfg = load_config()
        print(f"Provider: {cfg.llm_provider}")
        print(f"Model:    {cfg.llm_model}")
        print("Testing LLM completion...")
        try:
            res = complete_json("Reply with JSON: {\"status\": \"ok\"}", {"status": str}, config=cfg)
            print(f"Result:   SUCCESS ({res})")
        except Exception as exc:
            print(f"Result:   FAILED ({exc})")
