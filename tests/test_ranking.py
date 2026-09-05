"""Need-aware ranking: the economic reasoning that replaces the single-provider gate."""

from __future__ import annotations

import pytest

from ledger402 import confidence as conf, ranking
from ledger402.providers import get_provider, providers_for_category
from ledger402.tasks import PORT_CONGESTION, PORT_CONGESTION_SPEC as SPEC
from tests.test_confidence import FREE, SATELLITE

def _b2b_catalog():
    return [
        p
        for p in providers_for_category(PORT_CONGESTION)
        if not str(p.get("id") or "").startswith("b2c_")
    ]


def rank(**overrides):
    kwargs = dict(
        evidence=[FREE],
        spec=SPEC,
        current_confidence=conf.confidence([FREE], SPEC),
        target_confidence=0.92,
        remaining_budget_drops=5000,
    )
    kwargs.update(overrides)
    return ranking.rank_providers(_b2b_catalog(), **kwargs)


SATELLITE_META = get_provider("satellite_logistics_paid")
TELEMETRY_META = get_provider("terminal_telemetry_paid")


def test_free_providers_are_not_ranked():
    """Free sources are fetched unconditionally; only purchases need a decision."""
    assert {c.provider_id for c in rank().candidates} == {
        "satellite_logistics_paid",
        "terminal_telemetry_paid",
    }


def test_best_candidate_is_the_most_confidence_per_drop():
    """Not the cheapest: telemetry costs half as much and still loses."""
    best = rank().best
    assert best.provider_id == "satellite_logistics_paid"
    assert best.price_drops == 1200


def test_already_covered_evidence_has_no_marginal_value():
    """Re-buying signals the agent already holds is the classic way to waste money."""
    result = rank(
        evidence=[FREE, SATELLITE],
        current_confidence=conf.confidence([FREE, SATELLITE], SPEC),
    )
    satellite = next(
        c for c in result.candidates if c.provider_id == "satellite_logistics_paid"
    )
    assert satellite.marginal_gain == pytest.approx(0.0, abs=1e-6)
    assert not satellite.eligible


def test_purchased_providers_are_excluded():
    result = rank(already_purchased={"satellite_logistics_paid"})
    satellite = next(
        c for c in result.candidates if c.provider_id == "satellite_logistics_paid"
    )
    assert not satellite.eligible
    assert "Already purchased" in satellite.reason
    assert result.best.provider_id == "terminal_telemetry_paid"


def test_nothing_is_eligible_once_the_target_is_met():
    result = rank(current_confidence=0.95, target_confidence=0.85)
    assert result.best is None
    assert all("already meets" in c.reason for c in result.candidates)


def test_marginal_gain_below_the_floor_is_rejected():
    """A purchase must move the answer, not merely be affordable."""
    negligible = {
        **TELEMETRY_META,
        "signals": ["rail_dwell_hours"],
        "quality_score": 0.05,
    }
    result = ranking.rank_providers(
        [negligible],
        evidence=[FREE],
        spec=SPEC,
        current_confidence=conf.confidence([FREE], SPEC),
        target_confidence=0.92,
        remaining_budget_drops=5000,
    )
    assert result.best is None
    assert "below the" in result.candidates[0].reason


def test_budget_gates_the_expensive_provider():
    result = rank(remaining_budget_drops=800)
    assert result.best.provider_id == "terminal_telemetry_paid"
    satellite = next(
        c for c in result.candidates if c.provider_id == "satellite_logistics_paid"
    )
    assert "exceeds remaining procurement budget" in satellite.reason


def test_per_purchase_cap_gates_a_provider_the_budget_could_afford():
    """Budget and per-purchase cap are separate rails and must both apply."""
    result = rank(remaining_budget_drops=5000, max_single_purchase_drops=1000)
    assert result.best.provider_id == "terminal_telemetry_paid"
    satellite = next(
        c for c in result.candidates if c.provider_id == "satellite_logistics_paid"
    )
    assert "max single purchase" in satellite.reason


def test_ranking_is_serialisable_for_the_ui():
    payload = rank().to_list()
    assert payload[0]["provider_id"] == "satellite_logistics_paid"
    for entry in payload:
        assert {"marginal_confidence_gain", "confidence_per_1000_drops", "eligible", "reason"} <= set(entry)


def test_rejected_candidates_are_still_reported():
    """The UI must be able to show what the agent declined to buy, and why."""
    result = rank(remaining_budget_drops=800)
    assert len(result.candidates) == 2
    assert any(not c.eligible for c in result.candidates)
