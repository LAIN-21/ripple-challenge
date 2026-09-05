"""Gemini-only provider and model cascade."""

from __future__ import annotations

import pytest

from ledger402 import llm


def test_no_key_means_disabled():
    assert not llm.is_enabled()
    assert llm.model_name() == ""
    assert llm.provider_name() == ""


def test_gemini_key_enables_the_llm(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    assert llm.is_enabled()
    assert llm.provider_name() == "gemini"
    assert llm.model_name() == "gemini-2.5-flash"


def test_default_cascade_order(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    assert llm.model_cascade() == (
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
    )


def test_custom_model_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    assert llm.model_name() == "gemini-2.5-pro"
    assert llm.model_cascade() == ("gemini-2.5-pro",)


def test_comma_separated_model_env_becomes_a_custom_cascade(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash, gemini-1.5-flash")
    assert llm.model_cascade() == ("gemini-2.5-flash", "gemini-1.5-flash")


class _ServerOverloaded(Exception):
    def __init__(self, status_code=503):
        super().__init__("high demand")
        self.status_code = status_code


class _AuthFailed(Exception):
    def __init__(self):
        super().__init__("invalid api key")
        self.status_code = 401


def test_first_model_success_never_touches_the_rest_of_the_cascade(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    calls = []

    def generate(model, system, user):
        calls.append(model)
        return "hello"

    monkeypatch.setattr(llm, "_generate", generate)
    assert llm.complete("sys", "usr") == "hello"
    assert calls == ["gemini-2.5-flash"]


def test_capacity_error_falls_back_to_the_next_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    calls = []

    def generate(model, system, user):
        calls.append(model)
        if model == "gemini-2.5-flash":
            raise _ServerOverloaded()
        return "ok"

    monkeypatch.setattr(llm, "_generate", generate)
    assert llm.complete("sys", "usr") == "ok"
    assert calls == ["gemini-2.5-flash", "gemini-2.5-pro"]


def test_cascade_exhaustion_raises_llm_unavailable(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setattr(
        llm, "_generate", lambda model, system, user: (_ for _ in ()).throw(_ServerOverloaded())
    )
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "usr")


def test_non_retryable_error_does_not_cascade(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    calls = []

    def generate(model, system, user):
        calls.append(model)
        raise _AuthFailed()

    monkeypatch.setattr(llm, "_generate", generate)
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "usr")
    assert calls == ["gemini-2.5-flash"]


def test_connection_errors_are_treated_as_retryable(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")

    class APIConnectionError(Exception):
        pass

    calls = []

    def generate(model, system, user):
        calls.append(model)
        if len(calls) == 1:
            raise APIConnectionError("connection reset")
        return "ok"

    monkeypatch.setattr(llm, "_generate", generate)
    assert llm.complete("sys", "usr") == "ok"


def test_complete_raises_when_the_response_is_empty(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
    monkeypatch.setattr(llm, "_generate", lambda model, system, user: "   ")
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("sys", "usr")


def test_missing_google_genai_reports_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")

    import builtins
    import sys

    monkeypatch.delitem(sys.modules, "google", raising=False)
    monkeypatch.delitem(sys.modules, "google.genai", raising=False)
    monkeypatch.delitem(sys.modules, "google.genai.types", raising=False)

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "google" or name.startswith("google."):
            raise ImportError("simulated: not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(llm.LLMUnavailable, match="google-genai"):
        llm.complete("sys", "usr")
