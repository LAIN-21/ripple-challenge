"""Provider selection: Groq preferred, Gemini as a drop-in fallback, no key = disabled.

Both providers speak the OpenAI-compatible chat completion protocol, so the contract the
rest of the codebase depends on (is_enabled/complete/complete_json) must behave
identically regardless of which one answered.
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
    assert llm.model_name() == llm.GROQ.default_model


def test_gemini_key_alone_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    assert llm.is_enabled()
    assert llm.provider_name() == "gemini"
    assert llm.model_name() == llm.GEMINI.default_model


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


def test_provider_specs_use_openai_compatible_endpoints():
    """Both providers must expose the OpenAI-compatible surface llm.py relies on."""
    for provider in llm.PROVIDERS:
        assert provider.base_url.rstrip("/").endswith(("v1", "openai"))


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeClient:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return _FakeMessage(self._content)


def test_complete_works_identically_regardless_of_provider(monkeypatch):
    for key_env, value in (("GROQ_API_KEY", "gsk_test"), ("GEMINI_API_KEY", "AIza_test")):
        monkeypatch.setenv(key_env, value)
        monkeypatch.setattr(llm, "_client", lambda: _FakeClient("hello"))
        assert llm.complete("sys", "usr") == "hello"
        monkeypatch.delenv(key_env, raising=False)


def test_complete_raises_when_the_response_is_empty(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(llm, "_client", lambda: _FakeClient("   "))
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
        llm._client()
