"""End-to-end tests for the agentic loop.

Never spends Testnet XRP: the payment boundary is mocked at
`ledger402.payment.purchase_premium`, and the public fetch at `graph.requests.get`.
"""

from __future__ import annotations

import pytest

from ledger402 import audit, graph, payment

FREE_PAYLOAD = {
    "provider_id": "public-port-stats",
    "provider_name": "Public Port Statistics",
    "port": "Port X",
    "berth_occupancy": 0.71,
    "average_wait_hours": 8.4,
    "vessel_queue": 17,
    "freshness_hours": 72,
    "quality_score": 0.62,
    "synthetic": True,
}

SATELLITE_PAYLOAD = {
    "provider_id": "satellite-logistics-intel",
    "provider_name": "Satellite Logistics Intelligence",
    "port": "Port X",
    "container_density_delta": 0.24,
    "anchored_vessels_delta": 0.31,
    "yard_utilization": 0.91,
    "truck_activity_delta": 0.18,
    "freshness_hours": 3,
    "quality_score": 0.93,
    "synthetic": True,
}

TELEMETRY_PAYLOAD = {
    "provider_id": "terminal-ops-telemetry",
    "provider_name": "Terminal Operations Telemetry",
    "port": "Port X",
    "gate_turnaround_minutes": 84,
    "rail_dwell_hours": 41.5,
    "freshness_hours": 6,
    "quality_score": 0.81,
    "synthetic": True,
}

QUESTION = "Assess whether Port X is becoming congested."


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return dict(self._payload)


@pytest.fixture
def free_provider_up(monkeypatch):
    monkeypatch.setattr(
        graph.requests, "get", lambda url, timeout=None: _FakeResponse(FREE_PAYLOAD)
    )


@pytest.fixture
def paying_agent(monkeypatch, free_provider_up):
    """Mock settlement: each provider returns its payload and a distinct tx hash."""
    calls: list[str] = []
    bodies = {
        "satellite-logistics-intel": SATELLITE_PAYLOAD,
        "terminal-ops-telemetry": TELEMETRY_PAYLOAD,
    }
    hashes = {
        "satellite-logistics-intel": "A" * 64,
        "terminal-ops-telemetry": "B" * 64,
    }

    def fake_purchase(*, provider_id, **kwargs):
        calls.append(provider_id)
        return payment.PurchaseRecord(
            state=payment.SUCCESS,
            tx_hash=hashes[provider_id],
            body=dict(bodies[provider_id]),
            network_fee_drops=12,
        )

    monkeypatch.setattr(payment, "purchase_premium", fake_purchase)
    return calls


# ------------------------------------------------------------------ fail closed


def test_unsupported_question_fails_closed(free_provider_up):
    result = graph.run_agent(question="Should we enter the Japanese market?")
    assert result["status_code"] == 400
    assert result["error"] == "unsupported_task"
    # It must not leak Port X evidence into an unrelated answer.
    assert "report" not in result


def test_unsupported_task_type_is_rejected(free_provider_up):
    result = graph.run_agent(question=QUESTION, task_type="equities")
    assert result["status_code"] == 400
    assert result["error"] == "unsupported_task"


# ------------------------------------------------------- canonical demo figures


def test_public_only_run_reaches_58_percent(monkeypatch, free_provider_up):
    """With no purchase possible, the agent reports the documented 58%."""
    monkeypatch.setattr(
        payment,
        "purchase_premium",
        lambda **kwargs: payment.PurchaseRecord(state=payment.FAILED, error="down"),
    )
    result = graph.run_agent(question=QUESTION, budget_drops=5000)
    assert round(result["initial_confidence"], 2) == 0.58
    assert result["settlement_count"] == 0
    assert result["spent_drops"] == 0
    assert result["report"]["method"] == "template"


def test_default_target_buys_satellite_only(paying_agent):
    """The documented morning demo, now as an outcome rather than a script."""
    result = graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.85)

    assert round(result["initial_confidence"], 2) == 0.58
    assert round(result["final_confidence"], 2) == 0.87
    assert result["objective_met"] is True
    assert result["settlement_count"] == 1
    assert result["spent_drops"] == 1200
    assert result["remaining_budget_drops"] == 3800
    assert paying_agent == ["satellite-logistics-intel"]


def test_higher_target_buys_a_second_provider(paying_agent):
    """Same agent, same code: a stricter objective produces a second settlement."""
    result = graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.92)

    assert result["settlement_count"] == 2
    assert result["spent_drops"] == 1800
    assert result["remaining_budget_drops"] == 3200
    assert round(result["final_confidence"], 2) == 0.92
    # Highest confidence-per-drop first, not cheapest first.
    assert paying_agent == ["satellite-logistics-intel", "terminal-ops-telemetry"]


def test_agent_stops_when_no_provider_is_worth_buying(paying_agent):
    """An unreachable target stops the loop instead of draining the budget."""
    result = graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.99)

    assert result["objective_met"] is False
    # It buys everything useful, then stops rather than re-buying.
    assert result["settlement_count"] == 2
    assert "No remaining provider" in (result["stop_reason"] or "")


# --------------------------------------------------------------- spending rails


def test_max_purchases_ceiling_is_enforced(paying_agent):
    result = graph.run_agent(
        question=QUESTION, budget_drops=5000, target_confidence=0.99, max_purchases=1
    )
    assert result["settlement_count"] == 1
    assert result["spent_drops"] == 1200


def test_budget_too_small_prevents_any_purchase(paying_agent):
    """Policy rejects both providers; the agent answers from public evidence."""
    result = graph.run_agent(question=QUESTION, budget_drops=500, target_confidence=0.92)
    assert result["settlement_count"] == 0
    assert result["spent_drops"] == 0
    assert paying_agent == []
    assert round(result["final_confidence"], 2) == 0.58


def test_budget_allows_only_the_cheaper_provider(paying_agent):
    """With 800 drops the satellite feed is unaffordable, so telemetry is bought."""
    result = graph.run_agent(question=QUESTION, budget_drops=800, target_confidence=0.92)
    assert paying_agent == ["terminal-ops-telemetry"]
    assert result["spent_drops"] == 600
    assert result["remaining_budget_drops"] == 200


# -------------------------------------------------------------- failure handling


def test_payment_failure_degrades_to_public_only(monkeypatch, free_provider_up):
    monkeypatch.setattr(
        payment,
        "purchase_premium",
        lambda **kwargs: payment.PurchaseRecord(
            state=payment.FAILED, error="XRPL payment failed"
        ),
    )
    result = graph.run_agent(question=QUESTION, budget_drops=5000, run_id="fail-run")

    assert result["settlement_count"] == 0
    assert result["spent_drops"] == 0
    assert round(result["final_confidence"], 2) == 0.58
    assert result["report"] is not None


def test_failed_provider_is_not_retried_in_the_same_run(monkeypatch, free_provider_up):
    """A failing provider must not spin the loop; each is attempted at most once."""
    attempts: list[str] = []

    def always_fails(*, provider_id, **kwargs):
        attempts.append(provider_id)
        return payment.PurchaseRecord(state=payment.FAILED, error="down")

    monkeypatch.setattr(payment, "purchase_premium", always_fails)
    graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.95)

    assert sorted(attempts) == ["satellite-logistics-intel", "terminal-ops-telemetry"]


def test_missing_wallet_is_a_config_error_not_a_crash(monkeypatch, free_provider_up):
    monkeypatch.delenv("XRPL_WALLET_SEED", raising=False)
    monkeypatch.delenv("XRPL_PAY_TO", raising=False)

    result = graph.run_agent(question=QUESTION, budget_drops=5000, run_id="cfg-run")

    assert result["settlement_count"] == 0
    assert "wallet configuration missing" in (result["stop_reason"] or "").lower()
    assert result["report"] is not None


def test_blocked_network_is_fatal_and_does_not_try_remaining_providers(
    monkeypatch, free_provider_up
):
    """CONFIG_ERROR must stop the loop; ranking the next provider would bury the reason."""
    attempts: list[str] = []

    def blocked(*, provider_id, **kwargs):
        attempts.append(provider_id)
        return payment.PurchaseRecord(
            state=payment.CONFIG_ERROR,
            error="Refusing to sign: Ledger402 settles on XRPL test networks only.",
        )

    monkeypatch.setattr(payment, "purchase_premium", blocked)
    result = graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.95)

    assert attempts == ["satellite-logistics-intel"]
    assert "test networks only" in (result["stop_reason"] or "")
    assert "test networks only" in (result["configuration_error"] or "")
    assert "No remaining provider" not in (result["stop_reason"] or "")
    types = [event["type"] for event in result["event_log"]]
    assert "PROCUREMENT_ABORTED" in types


def test_public_source_down_still_produces_an_answer(monkeypatch):
    def boom(url, timeout=None):
        raise RuntimeError("free provider down")

    monkeypatch.setattr(graph.requests, "get", boom)
    monkeypatch.setattr(
        payment,
        "purchase_premium",
        lambda **kwargs: payment.PurchaseRecord(
            state=payment.SUCCESS, tx_hash="C" * 64, body=dict(SATELLITE_PAYLOAD)
        ),
    )
    result = graph.run_agent(question=QUESTION, budget_drops=5000)

    assert result["report"] is not None
    types = [event["type"] for event in result["event_log"]]
    assert "PUBLIC_SOURCE_UNAVAILABLE" in types


# ------------------------------------------------------------------ idempotency


def test_same_run_id_does_not_settle_twice(monkeypatch, free_provider_up):
    """Process-local idempotency survives the loop: the cache is the guard."""
    real_calls = {"n": 0}

    def counting_purchase(*, run_id, provider_id, **kwargs):
        key = f"{run_id}:{provider_id}"
        cached = payment._cache.get(key)
        if cached and cached.state in {payment.PENDING, payment.SUCCESS, payment.UNKNOWN}:
            return cached
        real_calls["n"] += 1
        record = payment.PurchaseRecord(
            state=payment.SUCCESS, tx_hash="D" * 64, body=dict(SATELLITE_PAYLOAD)
        )
        payment._cache[key] = record
        return record

    monkeypatch.setattr(payment, "purchase_premium", counting_purchase)

    first = graph.run_agent(question=QUESTION, budget_drops=5000, run_id="dup-run")
    second = graph.run_agent(question=QUESTION, budget_drops=5000, run_id="dup-run")

    assert first["transaction_hashes"] == ["D" * 64]
    assert second["transaction_hashes"] == ["D" * 64]
    assert real_calls["n"] == 1


# ----------------------------------------------------------------- audit anchor


def test_audit_anchor_is_reproducible(paying_agent):
    result = graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.85)
    anchor = result["audit_anchor"]

    assert anchor["settlement_count"] == 1
    assert anchor["algorithm"] == "SHA-256"
    assert len(anchor["audit_hash"]) == 64

    dossier = "\n".join(
        [
            result["report"]["congestion_risk"],
            result["report"]["summary"],
            *sorted(result["report"]["evidence"]),
        ]
    )
    assert audit.verify_audit_anchor(anchor, dossier)


def test_audit_anchor_marks_an_unbacked_report(monkeypatch, free_provider_up):
    monkeypatch.setattr(
        payment,
        "purchase_premium",
        lambda **kwargs: payment.PurchaseRecord(state=payment.FAILED, error="down"),
    )
    result = graph.run_agent(question=QUESTION, budget_drops=5000)
    assert result["audit_anchor"]["settlement_count"] == 0
    assert result["audit_anchor"]["folded_tx_hashes"] == "0" * 64


# ------------------------------------------------------------------- audit trail


def test_event_log_records_the_decision_path(paying_agent):
    result = graph.run_agent(question=QUESTION, budget_drops=5000, target_confidence=0.85)
    types = [event["type"] for event in result["event_log"]]

    for expected in (
        "RESEARCH_REQUEST_UNDERSTOOD",
        "PROVIDERS_DISCOVERED",
        "PUBLIC_SOURCE_QUERIED",
        "CONFIDENCE_ASSESSED",
        "PROVIDERS_RANKED",
        "PURCHASE_APPROVED",
        "OBJECTIVE_MET",
        "REPORT_SYNTHESIZED",
        "AUDIT_ANCHOR_COMPUTED",
    ):
        assert expected in types, f"missing {expected}"

    assert all(event.get("at") for event in result["event_log"])
