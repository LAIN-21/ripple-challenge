"""Per-event snapshots must describe the moment of the event, not the end of the node.

LangGraph emits state only after a whole node finishes. The procure node emits four
events and spends money inside one node, so a naive snapshot would show the budget
already drained while the agent was merely observing the 402 — visibly wrong on the live
view, and it undercuts the story the animation is telling.
"""

from __future__ import annotations

import pytest

from ledger402 import graph
from tests.test_graph import (
    QUESTION,
    free_provider_up,  # noqa: F401 - fixture
)


@pytest.fixture(autouse=True)
def _stack(free_provider_up, settling_agent):  # noqa: F811
    """Real payment control flow, real audit events, no signing and no XRP spent."""
    return settling_agent


def events_of(**kwargs):
    chunks = list(graph.stream_agent(question=QUESTION, budget_drops=5000, **kwargs))
    return [c for c in chunks if c["kind"] == "event"]


def test_budget_is_untouched_until_the_payment_confirms():
    events = events_of(target_confidence=0.85)
    by_type = {e["event"]["type"]: e["snapshot"] for e in events}

    # The agent has seen the price but not paid it yet.
    assert by_type["HTTP_402_OBSERVED"]["spent_drops"] == 0
    assert by_type["HTTP_402_OBSERVED"]["settlement_count"] == 0
    assert by_type["X402_PAYMENT_NEGOTIATION_STARTED"]["spent_drops"] == 0

    # Only once the ledger confirms does the budget move.
    assert by_type["XRPL_PAYMENT_CONFIRMED"]["spent_drops"] == 1200
    assert by_type["XRPL_PAYMENT_CONFIRMED"]["settlement_count"] == 1
    assert by_type["XRPL_PAYMENT_CONFIRMED"]["remaining_budget_drops"] == 3800


def test_confidence_only_rises_at_the_assessment():
    """Unlocking data does not raise confidence; re-measuring it does."""
    events = events_of(target_confidence=0.85)
    seq = [(e["event"]["type"], e["snapshot"]["confidence"]) for e in events]

    unlocked = next(c for t, c in seq if t == "PREMIUM_RESOURCE_UNLOCKED")
    assert round(unlocked, 2) == 0.58

    assessments = [c for t, c in seq if t == "CONFIDENCE_ASSESSED"]
    assert round(assessments[0], 2) == 0.58
    assert round(assessments[1], 2) == 0.87


def test_snapshots_are_monotonic_across_two_settlements():
    events = events_of(target_confidence=0.92)
    spent = [e["snapshot"]["spent_drops"] for e in events]
    settled = [e["snapshot"]["settlement_count"] for e in events]
    confidence = [e["snapshot"]["confidence"] for e in events]

    # A live gauge must never jump backwards.
    assert spent == sorted(spent)
    assert settled == sorted(settled)
    assert confidence == sorted(confidence)

    assert spent[0] == 0 and spent[-1] == 1800
    assert settled[-1] == 2


def test_remaining_budget_always_complements_spend():
    for event in events_of(target_confidence=0.92):
        s = event["snapshot"]
        assert s["spent_drops"] + s["remaining_budget_drops"] == s["budget_drops"]


def test_snapshot_matches_the_final_result():
    """The last snapshot and the authoritative result must not disagree."""
    chunks = list(graph.stream_agent(question=QUESTION, budget_drops=5000, target_confidence=0.92))
    last = [c for c in chunks if c["kind"] == "event"][-1]["snapshot"]
    result = chunks[-1]["result"]

    assert last["spent_drops"] == result["spent_drops"]
    assert last["remaining_budget_drops"] == result["remaining_budget_drops"]
    assert last["settlement_count"] == result["settlement_count"]
    assert round(last["confidence"], 4) == round(result["final_confidence"], 4)


def test_failed_payment_does_not_move_the_budget(monkeypatch):
    from ledger402 import payment

    monkeypatch.setattr(
        payment,
        "purchase_premium",
        lambda **kwargs: payment.PurchaseRecord(state=payment.FAILED, error="down"),
    )
    for event in events_of(target_confidence=0.92):
        assert event["snapshot"]["spent_drops"] == 0
        assert event["snapshot"]["settlement_count"] == 0
