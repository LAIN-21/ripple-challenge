"""The confidence model, including the calibration the demo figures depend on."""

from __future__ import annotations

import pytest

from ledger402 import confidence as conf
from ledger402.confidence import EvidenceItem
from ledger402.providers import get_provider
from ledger402.tasks import CORE_SIGNAL_WEIGHTS, PORT_CONGESTION_SPEC as SPEC

FREE = EvidenceItem(
    provider_id="public_port_stats",
    provider_name="Public Port Statistics",
    payload={
        "berth_occupancy": 0.71,
        "average_wait_hours": 8.4,
        "vessel_queue": 17,
        "freshness_hours": 72,
        "quality_score": 0.62,
        "port_code": "SGSIN",
    },
)

SATELLITE = EvidenceItem(
    provider_id="satellite_logistics_paid",
    provider_name="Satellite Logistics Intelligence",
    payload={
        "yard_utilization": 0.91,
        "anchored_vessels_delta": 0.31,
        "container_density_delta": 0.24,
        "truck_activity_delta": 0.18,
        "freshness_hours": 3,
        "quality_score": 0.93,
        "port_code": "SGSIN",
    },
    paid=True,
    price_drops=1200,
)

TELEMETRY = EvidenceItem(
    provider_id="terminal_telemetry_paid",
    provider_name="Terminal Operations Telemetry",
    payload={
        "gate_turnaround_minutes": 84,
        "rail_dwell_hours": 41.5,
        "freshness_hours": 6,
        "quality_score": 0.81,
        "port_code": "SGSIN",
    },
    paid=True,
    price_drops=600,
)


def test_task_weights_sum_to_one():
    """Coverage is only interpretable if the core B2B weights form a full partition."""
    assert sum(CORE_SIGNAL_WEIGHTS.values()) == pytest.approx(1.0)


def test_calibration_reproduces_the_documented_demo_figures():
    assert round(conf.confidence([FREE], SPEC), 2) == 0.58
    assert round(conf.confidence([FREE, SATELLITE], SPEC), 2) == 0.87
    assert round(conf.confidence([FREE, SATELLITE, TELEMETRY], SPEC), 2) == 0.92


def test_no_evidence_is_zero_confidence():
    assert conf.confidence([], SPEC) == 0.0


def test_stale_evidence_is_worth_less_than_fresh_evidence():
    stale = EvidenceItem(
        provider_id="s",
        provider_name="s",
        payload={**SATELLITE.payload, "freshness_hours": 90},
    )
    assert conf.confidence([stale], SPEC) < conf.confidence([SATELLITE], SPEC)


def test_evidence_older_than_the_horizon_adds_nothing():
    expired = EvidenceItem(
        provider_id="s",
        provider_name="s",
        payload={**SATELLITE.payload, "freshness_hours": 200},
    )
    assert conf.credibility(0.93, 200) == 0.0
    assert conf.confidence([FREE, expired], SPEC) == conf.confidence([FREE], SPEC)


def test_duplicate_signals_take_the_best_source_not_the_sum():
    """Two sources of the same signal must not double-count into false certainty."""
    twin = EvidenceItem(
        provider_id="twin", provider_name="twin", payload=dict(SATELLITE.payload)
    )
    assert conf.confidence([SATELLITE], SPEC) == conf.confidence([SATELLITE, twin], SPEC)


def test_a_lower_quality_duplicate_does_not_reduce_confidence():
    weaker = EvidenceItem(
        provider_id="weak",
        provider_name="weak",
        payload={**SATELLITE.payload, "quality_score": 0.30},
    )
    assert conf.confidence([SATELLITE, weaker], SPEC) == conf.confidence([SATELLITE], SPEC)


def test_non_numeric_and_boolean_values_are_not_counted_as_signals():
    """`synthetic: true` must never be mistaken for a delivered measurement."""
    junk = EvidenceItem(
        provider_id="junk",
        provider_name="junk",
        payload={
            "yard_utilization": "high",
            "anchored_vessels_delta": None,
            "container_density_delta": True,
            "quality_score": 0.99,
            "freshness_hours": 1,
        },
    )
    assert conf.coverage_score([junk], SPEC) == 0.0


def test_confidence_never_exceeds_the_ceiling():
    perfect = [
        EvidenceItem(
            provider_id="p",
            provider_name="p",
            payload={
                **{signal: 1.0 for signal in SPEC.signal_weights},
                "quality_score": 1.0,
                "freshness_hours": 0,
            },
        )
    ]
    assert conf.confidence(perfect, SPEC) <= conf.CONFIDENCE_CEILING


def test_projected_confidence_matches_the_realised_value_when_delivery_is_honest():
    """The buy decision is only sound if the projection tracks what actually arrives."""
    projected = conf.projected_confidence([FREE], get_provider("satellite_logistics_paid"), SPEC)
    realised = conf.confidence([FREE, SATELLITE], SPEC)
    assert projected == pytest.approx(realised, abs=0.001)


def test_projection_does_not_survive_an_under_delivering_provider():
    """A provider that promises signals it does not send loses the credit after payment."""
    promised = conf.projected_confidence([FREE], get_provider("satellite_logistics_paid"), SPEC)
    delivered = EvidenceItem(
        provider_id="satellite_logistics_paid",
        provider_name="Satellite Logistics Intelligence",
        payload={"yard_utilization": 0.91, "freshness_hours": 3, "quality_score": 0.93},
        paid=True,
        price_drops=1200,
    )
    assert conf.confidence([FREE, delivered], SPEC) < promised


def test_uncertainty_gap_is_never_negative():
    assert conf.uncertainty_gap(0.90, 0.85) == 0.0
    assert conf.uncertainty_gap(0.58, 0.85) == pytest.approx(0.27)
