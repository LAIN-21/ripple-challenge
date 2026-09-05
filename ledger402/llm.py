"""LLM access, with deterministic degradation.

The agent must run with no API key, no network, and no LLM. Every call site here has a
deterministic fallback, so an LLM outage degrades the prose and never the spend: the LLM
classifies questions and writes reports, it never decides to pay.

Two providers are supported, both through their OpenAI-compatible chat completion
endpoint, so one client class covers either:

  - Groq: the hackathon's provided inference stack (LPU hardware, low latency).
  - Gemini: Google's API, also OpenAI-compatible, used when Groq credits are not
    available. See https://ai.google.dev/gemini-api/docs/openai

Within whichever provider is active, each call tries a small cascade of models rather
than one fixed model. A model returning 503/429 ("high demand") is a capacity problem
with that specific model, not with the account or the provider — a sibling model usually
has separate capacity and answers immediately. This is a fallback, not a retry: no
backoff or repeated attempts against the same model, because a live demo needs an answer
in seconds, not after several timeouts.

Whichever model ultimately answers, the contract with the rest of the codebase is
identical: `is_enabled()`, `complete()`, `complete_json()`. Callers do not know or care
which provider or model answered.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# LLM calls sit on the demo's critical path; fail fast rather than hang the UI. Each
# model in the cascade gets exactly one attempt (no built-in retries) so a stuck model
# costs one timeout, not several, before the cascade moves on.
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_RETRIES = 0


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    base_url: str
    # Tried in order. The first entry is the "primary" model shown by model_name();
    # later entries are capacity fallbacks, not quality downgrades chosen lightly.
    models: tuple[str, ...]
    model_env: str


GROQ = ProviderSpec(
    name="groq",
    key_env="GROQ_API_KEY",
    base_url="https://api.groq.com/openai/v1",
    models=(
        "llama-3.3-70b-versatile",  # primary: most capable
        "llama-3.1-8b-instant",  # fallback: smaller, separate capacity pool, still fast
    ),
    model_env="GROQ_MODEL",
)

GEMINI = ProviderSpec(
    name="gemini",
    key_env="GEMINI_API_KEY",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    models=(
        "gemini-3.5-flash",  # primary: current stable Flash tier
        "gemini-3.7-flash",  # fallback: different model family, separate capacity
        "gemini-3.5-flash-lite",  # fallback: lighter tier, usually has headroom
        "gemini-2.5-flash",  # last resort: previous generation, most likely to be free
        # (2.5-flash is scheduled to retire ~Oct 2026; kept as the final rung only
        # because it is otherwise the most likely to have spare capacity today)
    ),
    model_env="GEMINI_MODEL",
)

# Order expresses preference when more than one key is present: Groq is the hackathon's
# provided stack (and lower latency), so it wins a tie. LLM_PROVIDER overrides this.
PROVIDERS = (GROQ, GEMINI)

# HTTP statuses that mean "this model is temporarily out of capacity", not "your request
# or key is invalid". Only these advance the cascade to the next model.
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


class LLMUnavailable(RuntimeError):
    """No usable LLM: missing key, missing package, or every model in the cascade failed."""


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


def model_cascade(provider: ProviderSpec) -> tuple[str, ...]:
    """The models to try, in order, for `provider`.

    GROQ_MODEL / GEMINI_MODEL overrides the whole cascade: a comma-separated list
    becomes a custom cascade, and a single value becomes a cascade of one (explicit
    means explicit — no silent fallback to models the operator did not ask for).
    """
    override = (os.getenv(provider.model_env) or "").strip()
    if not override:
        return provider.models
    return tuple(m.strip() for m in override.split(",") if m.strip())


def model_name() -> str:
    """The primary (first-choice) model for display. See model_cascade() for the rest."""
    provider = active_provider()
    if provider is None:
        return ""
    cascade = model_cascade(provider)
    return cascade[0] if cascade else ""


def provider_name() -> str:
    provider = active_provider()
    return provider.name if provider else ""


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status in _RETRYABLE_STATUS_CODES
    # Connection-level failures (DNS, timeout, reset) carry no status code but are just
    # as much a "try the next model" situation as a 503 is.
    type_name = type(exc).__name__
    return type_name in {"APIConnectionError", "APITimeoutError", "Timeout"}


def _build_client(provider: ProviderSpec, model: str) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is pinned in requirements
        raise LLMUnavailable(f"langchain-openai is not installed: {exc}") from exc

    return ChatOpenAI(
        model=model,
        api_key=_configured_key(provider),
        base_url=provider.base_url,
        temperature=0.0,
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS),
        max_retries=int(os.getenv("LLM_MAX_RETRIES") or DEFAULT_MAX_RETRIES),
    )


def complete(system: str, user: str) -> str:
    """One completion, cascading through models on capacity errors.

    Raises LLMUnavailable if no LLM is configured, if every model in the cascade is
    unavailable, or immediately on a non-capacity error (bad key, malformed request) —
    retrying that against a different model would not help and would only add latency.
    """
    provider = active_provider()
    if provider is None:
        raise LLMUnavailable("No LLM configured: set GROQ_API_KEY or GEMINI_API_KEY.")

    cascade = model_cascade(provider)
    if not cascade:
        raise LLMUnavailable(f"{provider.name}: no model configured.")

    last_exc: Exception | None = None
    for attempt, model in enumerate(cascade):
        try:
            client = _build_client(provider, model)
            response = client.invoke([("system", system), ("human", user)])
        except LLMUnavailable:
            raise
        except Exception as exc:
            if not _is_retryable(exc) or attempt == len(cascade) - 1:
                raise LLMUnavailable(f"{provider.name}/{model} call failed: {exc}") from exc
            log.info(
                "%s/%s unavailable (%s); falling back to %s",
                provider.name, model, exc, cascade[attempt + 1],
            )
            last_exc = exc
            continue

        text = _extract_text(response)
        if not text:
            if attempt == len(cascade) - 1:
                raise LLMUnavailable(f"{provider.name}/{model} returned an empty completion.")
            continue
        return text

    # Only reachable if every model returned an empty completion.
    raise LLMUnavailable(f"{provider.name}: every model in the cascade failed ({last_exc}).")


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        # Some providers return content blocks rather than a plain string.
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content).strip()


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
