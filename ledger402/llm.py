"""Groq LLM access, with deterministic degradation.

The agent must run with no API key, no network, and no LLM. Every call site here has a
deterministic fallback, so an LLM outage degrades the prose and never the spend: the LLM
classifies questions and writes reports, it never decides to pay.

Groq is the hackathon's provided inference stack (LPU, OpenAI-compatible endpoint).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

# LLM calls sit on the demo's critical path; fail fast rather than hang the UI.
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 1


class LLMUnavailable(RuntimeError):
    """No usable LLM: missing key, missing package, or a failed call."""


def is_enabled() -> bool:
    return bool((os.getenv("GROQ_API_KEY") or "").strip())


def model_name() -> str:
    return (os.getenv("GROQ_MODEL") or "").strip() or DEFAULT_MODEL


def _client() -> Any:
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set.")
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover - dependency is pinned in requirements
        raise LLMUnavailable(f"langchain-groq is not installed: {exc}") from exc

    kwargs: dict[str, Any] = {
        "model": model_name(),
        "api_key": api_key,
        "temperature": 0.0,
        "timeout": float(os.getenv("GROQ_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS),
        "max_retries": int(os.getenv("GROQ_MAX_RETRIES") or DEFAULT_MAX_RETRIES),
    }
    base_url = (os.getenv("GROQ_BASE_URL") or "").strip()
    if base_url and base_url != DEFAULT_BASE_URL:
        kwargs["base_url"] = base_url
    return ChatGroq(**kwargs)


def complete(system: str, user: str) -> str:
    """One completion. Raises LLMUnavailable on any failure; callers must fall back."""
    try:
        client = _client()
        response = client.invoke(
            [("system", system), ("human", user)]
        )
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(f"Groq call failed: {exc}") from exc

    content = getattr(response, "content", response)
    if isinstance(content, list):
        # Some providers return content blocks rather than a plain string.
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    text = str(content).strip()
    if not text:
        raise LLMUnavailable("Groq returned an empty completion.")
    return text


def _strip_code_fence(text: str) -> str:
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text.strip(), re.DOTALL)
    return fenced.group(1) if fenced else text


def complete_json(system: str, user: str) -> dict[str, Any]:
    """Completion parsed as a JSON object.

    Models wrap JSON in prose or code fences often enough that a bare json.loads is not
    reliable; the brace-span fallback keeps a good answer from being thrown away.
    """
    raw = _strip_code_fence(complete(system, user))
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise LLMUnavailable(f"Groq did not return JSON: {raw[:200]}")
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"Groq returned malformed JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMUnavailable("Groq returned JSON that is not an object.")
    return parsed
