"""Offline replay uses recorded Testnet hashes and never signs."""

from __future__ import annotations

import pytest

from providers_data import OFFLINE_REPLAY_SETTLEMENTS
from ledger402 import graph, payment, replay


SATELLITE_TX = OFFLINE_REPLAY_SETTLEMENTS["satellite_logistics_paid"]["tx_hash"]
CANONICAL = OFFLINE_REPLAY_SETTLEMENTS["canonical_target_92"]
QUESTION = "Assess whether Port of Singapore (PSA) is facing critical yard and terminal congestion"


@pytest.fixture
def forbid_live_purchase(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("replay must not call purchase_premium")

    monkeypatch.setattr(payment, "purchase_premium", boom)


def test_replay_085_uses_the_recorded_satellite_hash(forbid_live_purchase):
    result = graph.run_agent(
        question=QUESTION,
        budget_drops=5000,
        target_confidence=0.85,
        replay=True,
    )
    assert result["replay"] is True
    assert result["settlement_count"] == 1
    assert result["spent_drops"] == 1200
    assert result["transaction_hashes"] == [SATELLITE_TX]
    assert round(result["initial_confidence"], 2) == 0.58
    assert round(result["final_confidence"], 2) == 0.87


def test_replay_092_uses_canonical_two_settlement_hashes(forbid_live_purchase):
    result = graph.run_agent(
        question=QUESTION,
        budget_drops=5000,
        target_confidence=0.92,
        replay=True,
    )
    assert result["settlement_count"] == 2
    assert result["spent_drops"] == 1800
    assert result["transaction_hashes"] == [CANONICAL["tx_1"], CANONICAL["tx_2"]]
    assert round(result["final_confidence"], 2) == 0.92
    assert result["audit_anchor"]["settlement_count"] == 2


def test_replay_helper_picks_canonical_hashes_for_the_092_run():
    first = replay.settlement_for("satellite_logistics_paid", target_confidence=0.92, index=0)
    second = replay.settlement_for("terminal_telemetry_paid", target_confidence=0.92, index=1)
    assert first["tx_hash"] == CANONICAL["tx_1"]
    assert second["tx_hash"] == CANONICAL["tx_2"]
    single = replay.settlement_for("satellite_logistics_paid", target_confidence=0.85, index=0)
    assert single["tx_hash"] == SATELLITE_TX
    assert single["ledger_index"] == 20493969
