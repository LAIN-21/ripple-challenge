"""The two LLM-touching nodes, and the deterministic behaviour they fall back to.

These tests run with GROQ_API_KEY unset (see conftest), so they exercise the fallback
path the demo depends on, plus the guards that stop an LLM answer from widening what the
agent is willing to serve.
"""

from __future__ import annotations

import pytest

from ledger402 import classify, llm, synthesis
from ledger402.tasks import PORT_CONGESTION
from tests.test_confidence import FREE, SATELLITE

QUESTION = "Assess whether Port X is becoming congested."


# ------------------------------------------------------------------ classification


def test_port_question_is_classified_deterministically():
    result = classify.classify(QUESTION)
    assert result.task_type == PORT_CONGESTION
    assert result.supported
    assert result.method == "deterministic"
    assert result.subject == "Port X"


@pytest.mark.parametrize(
    "question",
    [
        "Should we enter the Japanese market?",
        "What is the yield on private credit?",
        "Is the port authority hiring?",  # mentions a port, but not congestion
    ],
)
def test_unrelated_questions_are_unsupported(question):
    assert not classify.classify(question).supported


def test_declared_unsupported_task_type_is_rejected_without_an_llm(monkeypatch):
    """An unsupported declaration short-circuits: no inference call is even attempted."""
    monkeypatch.setattr(
        llm, "complete_json", lambda *a, **k: pytest.fail("LLM must not be called")
    )
    result = classify.classify(QUESTION, declared_task_type="equities")
    assert not result.supported
    assert "not supported" in result.rationale


def test_llm_cannot_widen_the_supported_task_set(monkeypatch):
    """A hallucinated or injected task type is still rejected."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        llm,
        "complete_json",
        lambda *a, **k: {
            "task_type": "private_credit",
            "subject": "Anything",
            "confidence": 0.99,
            "rationale": "trust me",
        },
    )
    result = classify.classify("Assess private credit spreads.")
    assert not result.supported
    assert result.task_type == "unsupported"


def test_llm_failure_falls_back_to_the_rule(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def boom(*args, **kwargs):
        raise llm.LLMUnavailable("groq down")

    monkeypatch.setattr(llm, "complete_json", boom)
    result = classify.classify(QUESTION)
    assert result.supported
    assert result.method == "deterministic"


def test_llm_classification_is_used_when_available(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        llm,
        "complete_json",
        lambda *a, **k: {
            "task_type": PORT_CONGESTION,
            "subject": "Port Klang",
            "confidence": 0.91,
            "rationale": "Asks about berth pressure.",
        },
    )
    # Phrasing the keyword rule would miss, which is the reason to have an LLM at all.
    result = classify.classify("Are ships waiting longer than usual at Klang?")
    assert result.supported
    assert result.method == "llm"
    assert result.subject == "Port Klang"


# --------------------------------------------------------------------- synthesis


def test_template_report_reproduces_the_public_only_story():
    report = synthesis.synthesize([FREE], question=QUESTION, confidence=0.58, subject="Port X")
    assert report.method == "template"
    assert report.verdict == "MODERATE / UNCLEAR"
    assert "58%" in report.summary


def test_template_report_turns_high_once_satellite_evidence_arrives():
    report = synthesis.synthesize(
        [FREE, SATELLITE], question=QUESTION, confidence=0.87, subject="Port X"
    )
    assert report.verdict == "HIGH"
    assert any("Yard utilization: 91%" in line for line in report.evidence)
    assert any("paid source" in report.summary for _ in [0])


def test_report_always_declares_the_data_as_synthetic():
    report = synthesis.synthesize(
        [FREE, SATELLITE], question=QUESTION, confidence=0.87, subject="Port X"
    )
    assert any("synthetic" in caveat.lower() for caveat in report.caveats)


def test_no_evidence_produces_an_unclear_report_not_a_crash():
    report = synthesis.synthesize([], question=QUESTION, confidence=0.0, subject="Port X")
    assert report.verdict == "UNCLEAR"


def test_dossier_summary_is_order_independent():
    """The audit anchor is computed over this string; it must be stable."""
    report = synthesis.synthesize(
        [FREE, SATELLITE], question=QUESTION, confidence=0.87, subject="Port X"
    )
    shuffled = synthesis.Report(
        verdict=report.verdict,
        summary=report.summary,
        evidence=list(reversed(report.evidence)),
        caveats=report.caveats,
        method=report.method,
    )
    assert report.dossier_summary() == shuffled.dossier_summary()


def test_empty_llm_summary_falls_back_to_the_template(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"summary": "   "})
    report = synthesis.synthesize(
        [FREE, SATELLITE], question=QUESTION, confidence=0.87, subject="Port X"
    )
    assert report.method == "template"


def test_llm_report_keeps_the_synthetic_caveat(monkeypatch):
    """The LLM cannot drop the disclosure by omitting it."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        llm,
        "complete_json",
        lambda *a, **k: {
            "verdict": "HIGH",
            "summary": "Port X is congesting.",
            "evidence": ["Yard utilization 91% (Satellite)"],
            "caveats": [],
        },
    )
    report = synthesis.synthesize(
        [FREE, SATELLITE], question=QUESTION, confidence=0.87, subject="Port X"
    )
    assert report.method == "llm"
    assert any("synthetic" in caveat.lower() for caveat in report.caveats)


# ----------------------------------------------------------------- llm plumbing


def test_llm_is_disabled_without_a_key():
    assert not llm.is_enabled()


def test_complete_json_strips_code_fences(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: '```json\n{"ok": true}\n```')
    assert llm.complete_json("s", "u") == {"ok": True}


def test_complete_json_recovers_json_wrapped_in_prose(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: 'Sure!\n{"ok": true}\nHope that helps.')
    assert llm.complete_json("s", "u") == {"ok": True}


def test_complete_json_rejects_non_objects(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "[1, 2, 3]")
    with pytest.raises(llm.LLMUnavailable):
        llm.complete_json("s", "u")
