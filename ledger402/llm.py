"""LLM access via Google Gemini, with deterministic degradation.

The agent must run with no API key, no network, and no LLM. Every call site here has a
deterministic fallback, so an LLM outage degrades the prose and never the spend.

Cascade on transient capacity errors (one attempt each, no backoff):

    gemini-2.5-flash -> gemini-2.5-pro -> gemini-1.5-flash
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 12.0

GEMINI_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
)

_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


class LLMUnavailable(RuntimeError):
    """No usable LLM: missing key, missing package, or every model in the cascade failed."""


def _configured_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or "").strip()


def is_enabled() -> bool:
    return bool(_configured_key())


def model_cascade() -> tuple[str, ...]:
    override = (os.getenv("GEMINI_MODEL") or "").strip()
    if not override:
        return GEMINI_MODELS
    return tuple(m.strip() for m in override.split(",") if m.strip())


def model_name() -> str:
    cascade = model_cascade()
    return cascade[0] if cascade and is_enabled() else ""


def provider_name() -> str:
    return "gemini" if is_enabled() else ""


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and isinstance(details.get("code"), int):
        return int(details["code"])
    return None


def _is_retryable(exc: Exception) -> bool:
    status = _status_code(exc)
    if status is not None:
        return status in _RETRYABLE_STATUS_CODES
    type_name = type(exc).__name__
    return type_name in {
        "APIConnectionError",
        "APITimeoutError",
        "Timeout",
        "ServerError",
        "ConnectError",
    }


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    content = getattr(response, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", "") or ""))
        joined = "".join(parts).strip()
        if joined:
            return joined
    return ""


def _generate(model: str, system: str, user: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(f"google-genai is not installed: {exc}") from exc

    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    client = genai.Client(api_key=_configured_key())
    http_options = None
    try:
        http_options = types.HttpOptions(timeout=int(timeout * 1000))
    except Exception:
        http_options = None
    config_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "temperature": 0.0,
    }
    if http_options is not None:
        config_kwargs["http_options"] = http_options
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return _extract_text(response)


def complete(system: str, user: str) -> str:
    """One completion, cascading through Gemini models on capacity errors."""
    if not is_enabled():
        raise LLMUnavailable("No LLM configured: set GEMINI_API_KEY.")

    cascade = model_cascade()
    if not cascade:
        raise LLMUnavailable("gemini: no model configured.")

    last_exc: Exception | None = None
    for attempt, model in enumerate(cascade):
        try:
            text = _generate(model, system, user)
        except LLMUnavailable:
            raise
        except Exception as exc:
            if not _is_retryable(exc) or attempt == len(cascade) - 1:
                raise LLMUnavailable(f"gemini/{model} call failed: {exc}") from exc
            log.info(
                "gemini/%s unavailable (%s); falling back to %s",
                model,
                exc,
                cascade[attempt + 1],
            )
            last_exc = exc
            continue

        if not (text or "").strip():
            if attempt == len(cascade) - 1:
                raise LLMUnavailable(f"gemini/{model} returned an empty completion.")
            continue
        return text.strip()

    raise LLMUnavailable(f"gemini: every model in the cascade failed ({last_exc}).")


def _strip_code_fence(text: str) -> str:
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text.strip(), re.DOTALL)
    return fenced.group(1) if fenced else text


def complete_json(system: str, user: str) -> dict[str, Any]:
    raw = _strip_code_fence(complete(system, user))
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise LLMUnavailable(f"LLM did not return JSON: {raw[:200]}")
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"LLM returned malformed JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMUnavailable("LLM returned JSON that is not an object.")
    return parsed
