"""LLM access, with deterministic degradation.

The agent must run with no API key, no network, and no LLM. Every call site here has a
deterministic fallback, so an LLM outage degrades the prose and never the spend: the LLM
classifies questions and writes reports, it never decides to pay.

Two providers are supported, both through their OpenAI-compatible chat completion
endpoint, so one client class covers both:

  - Groq: the hackathon's provided inference stack (LPU hardware, low latency).
  - Gemini: Google's API, also OpenAI-compatible, used when Groq credits are not
    available. See https://ai.google.dev/gemini-api/docs/openai

Whichever is configured, the contract with the rest of the codebase is identical:
`is_enabled()`, `complete()`, `complete_json()`. Callers do not know or care which
provider answered.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# LLM calls sit on the demo's critical path; fail fast rather than hang the UI.
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 1


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    base_url: str
    default_model: str
    model_env: str


GROQ = ProviderSpec(
    name="groq",
    key_env="GROQ_API_KEY",
    base_url="https://api.groq.com/openai/v1",
    default_model="llama-3.3-70b-versatile",
    model_env="GROQ_MODEL",
)

GEMINI = ProviderSpec(
    name="gemini",
    key_env="GEMINI_API_KEY",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    # 2.5-flash is being retired (Oct 2026); 3.5-flash is the current stable Flash tier
    # and is available on Gemini's free tier.
    default_model="gemini-3.5-flash",
    model_env="GEMINI_MODEL",
)

# Order expresses preference when more than one key is present: Groq is the hackathon's
# provided stack (and lower latency), so it wins a tie. LLM_PROVIDER overrides this.
PROVIDERS = (GROQ, GEMINI)


class LLMUnavailable(RuntimeError):
    """No usable LLM: missing key, missing package, or a failed call."""


def _configured_key(provider: ProviderSpec) -> str:
    return (os.getenv(provider.key_env) or "").strip()


def active_provider() -> ProviderSpec | None:
    """Which provider is configured, honouring an explicit LLM_PROVIDER override."""
    forced = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if forced:
        match = next((p for p in PROVIDERS if p.name == forced), None)
        if match and _configured_key(match):
            return match
        return None  # An explicit choice with no key is not silently substituted.

    for provider in PROVIDERS:
        if _configured_key(provider):
            return provider
    return None


def is_enabled() -> bool:
    return active_provider() is not None


def model_name() -> str:
    provider = active_provider()
    if provider is None:
        return ""
    return (os.getenv(provider.model_env) or "").strip() or provider.default_model


def provider_name() -> str:
    provider = active_provider()
    return provider.name if provider else ""


def _client() -> Any:
    provider = active_provider()
    if provider is None:
        raise LLMUnavailable("No LLM configured: set GROQ_API_KEY or GEMINI_API_KEY.")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is pinned in requirements
        raise LLMUnavailable(f"langchain-openai is not installed: {exc}") from exc

    return ChatOpenAI(
        model=model_name(),
        api_key=_configured_key(provider),
        base_url=provider.base_url,
        temperature=0.0,
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS),
        max_retries=int(os.getenv("LLM_MAX_RETRIES") or DEFAULT_MAX_RETRIES),
    )


def complete(system: str, user: str) -> str:
    """One completion. Raises LLMUnavailable on any failure; callers must fall back."""
    provider = active_provider()
    try:
        client = _client()
        response = client.invoke([("system", system), ("human", user)])
    except LLMUnavailable:
        raise
    except Exception as exc:
        name = provider.name if provider else "LLM"
        raise LLMUnavailable(f"{name} call failed: {exc}") from exc

    content = getattr(response, "content", response)
    if isinstance(content, list):
        # Some providers return content blocks rather than a plain string.
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    text = str(content).strip()
    if not text:
        raise LLMUnavailable(f"{provider.name if provider else 'LLM'} returned an empty completion.")
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
            raise LLMUnavailable(f"LLM did not return JSON: {raw[:200]}")
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"LLM returned malformed JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMUnavailable("LLM returned JSON that is not an object.")
    return parsed
