"""Provider and model selection.

Groq preferred over Gemini when both are configured, no key means disabled, and within
whichever provider is active a small model cascade absorbs "this specific model is
overloaded" (503/429) without falling all the way back to the deterministic template.
"""

from __future__ import annotations

import pytest

from ledger402 import llm


def test_no_key_means_disabled():
    assert not llm.is_enabled()
    assert llm.active_provider() is None
    assert llm.model_name() == ""
    assert llm.provider_name() == ""


def test_groq_key_alone_selects_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert llm.is_enabled()
    assert llm.provider_name() == "groq"
    assert llm.model_name() == llm.GROQ.models[0]


def test_gemini_key_alone_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    assert llm.is_enabled()
    assert llm.provider_name() == "gemini"
    assert llm.model_name() == llm.GEMINI.models[0]


def test_groq_wins_when_both_keys_are_present(monkeypatch):
    """Groq is the hackathon's provided stack and lower latency; it wins ties."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    assert llm.provider_name() == "groq"


def test_llm_provider_env_forces_gemini_even_with_groq_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert llm.provider_name() == "gemini"


def test_forcing_a_provider_with_no_key_disables_the_llm(monkeypatch):
    """An explicit choice with no key must not silently fall back to another provider."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert not llm.is_enabled()


def test_custom_model_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    assert llm.model_name() == "gemini-3.1-flash-lite"
    assert llm.model_cascade(llm.GEMINI) == ("gemini-3.1-flash-lite",)


def test_comma_separated_model_env_becomes_a_custom_cascade(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash, gemini-2.5-flash")
    assert llm.model_cascade(llm.GEMINI) == ("gemini-3.5-flash", "gemini-2.5-flash")


def test_provider_specs_use_openai_compatible_endpoints():
    """Both providers must expose the OpenAI-compatible surface llm.py relies on."""
    for provider in llm.PROVIDERS:
        assert provider.base_url.rstrip("/").endswith(("v1", "openai"))
        assert len(provider.models) >= 1


# ---------------------------------------------------------------- model cascade


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeClient:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return _FakeMessage(self._content)


class _ServerOverloaded(Exception):
    """Stands in for openai.InternalServerError: has a retryable status_code."""

    def __init__(self, status_code=503):
        super().__init__("high demand")
        self.status_code = status_code


class _AuthFailed(Exception):
    """Stands in for openai.AuthenticationError: not retryable via a different model."""

    def __init__(self):
        super().__init__("invalid api key")
        self.status_code = 401


def _fake_cascade_client(responses: dict[str, object]):
    """responses maps model name -> either a string (success) or an Exception instance."""

    def build(provider, model):
        outcome = responses[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeClient(outcome)

    return build


def test_first_model_success_never_touches_the_rest_of_the_cascade(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    def build(provider, model):
        calls.append(model)
        return _FakeClient("hello")

    monkeypatch.setattr(llm, "_build_client", build)
    assert llm.complete("sys", "usr") == "hello"
    assert calls == [llm.GROQ.models[0]]


def test_capacity_error_falls_back_to_the_next_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    primary, fallback = llm.GROQ.models[0], llm.GROQ.models[1]
    monkeypatch.setattr(
        llm, "_build_client", _fake_cascade_client({primary: _ServerOverloaded(), fallback: "ok"})
    )
    assert llm.complete("sys", "usr") == "ok"


def test_cascade_exhaustion_raises_llm_unavailable(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setattr(
        llm, "_build_client", lambda provider, model: (_ for _ in ()).throw(_ServerOverloaded())
    )
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "usr")


def test_non_retryable_error_does_not_cascade(monkeypatch):
    """A bad key fails every model identically; trying the rest only wastes time."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    def build(provider, model):
        calls.append(model)
        raise _AuthFailed()

    monkeypatch.setattr(llm, "_build_client", build)
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "usr")
    assert calls == [llm.GROQ.models[0]]  # stopped after the first, did not try the rest


def test_custom_cascade_is_respected_in_order(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("GEMINI_MODEL", "model-a,model-b")
    monkeypatch.setattr(
        llm, "_build_client", _fake_cascade_client({"model-a": _ServerOverloaded(), "model-b": "ok"})
    )
    assert llm.complete("sys", "usr") == "ok"


def test_connection_errors_are_treated_as_retryable(monkeypatch):
    """No status_code at all (DNS/timeout) is still a reason to try the next model."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    primary, fallback = llm.GROQ.models[0], llm.GROQ.models[1]

    class APIConnectionError(Exception):
        pass

    monkeypatch.setattr(
        llm,
        "_build_client",
        _fake_cascade_client({primary: APIConnectionError("connection reset"), fallback: "ok"}),
    )
    assert llm.complete("sys", "usr") == "ok"


def test_complete_raises_when_the_response_is_empty(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(llm, "_build_client", lambda provider, model: _FakeClient("   "))
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "usr")


def test_missing_langchain_openai_reports_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "langchain_openai":
            raise ImportError("simulated: not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(llm.LLMUnavailable, match="langchain-openai"):
        llm.complete("sys", "usr")
