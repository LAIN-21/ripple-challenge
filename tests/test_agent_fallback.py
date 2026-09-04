from ledger402 import agent, payment
from ledger402.agent import run_research


def test_unsupported_question_fails_closed():
    result = run_research(
        question="Should we enter the Japanese market?",
        budget_drops=5000,
        task_type="port_congestion",
    )
    assert result["status_code"] == 400
    assert result["error"] == "unsupported_question"


def test_unsupported_task_type():
    result = run_research(
        question="Assess whether Port X is becoming congested.",
        budget_drops=5000,
        task_type="equities",
    )
    assert result["status_code"] == 400


def test_free_provider_failure_fallback(monkeypatch):
    monkeypatch.setattr(agent, "_fetch_json", lambda url, timeout=15.0: (_ for _ in ()).throw(RuntimeError("down")))
    result = run_research(
        question="Assess whether Port X is becoming congested.",
        budget_drops=5000,
    )
    assert result.get("error") == "free_provider_unavailable"


def test_payment_failure_returns_public_only(monkeypatch):
    payment.reset_cache()
    monkeypatch.setattr(
        agent,
        "_fetch_json",
        lambda url, timeout=15.0: {
            "freshness_hours": 72,
            "quality_score": 0.62,
            "synthetic": True,
        },
    )
    failed = payment.PurchaseRecord(state=payment.FAILED, error="XRPL payment failed")
    monkeypatch.setattr(agent.payment, "purchase_premium", lambda **kwargs: failed)
    result = run_research(
        question="Assess whether Port X is becoming congested.",
        budget_drops=5000,
        run_id="fallback-run",
    )
    assert result["fallback"] == "PUBLIC_ONLY"
    assert result["final_confidence"] == 0.58
    assert result["premium_purchase"] == payment.FAILED


def test_duplicate_purchase_reuses_success(monkeypatch):
    payment.reset_cache()
    record = payment.PurchaseRecord(
        state=payment.SUCCESS,
        tx_hash="ABC",
        body={
            "synthetic": True,
            "yard_utilization": 0.91,
            "anchored_vessels_delta": 0.31,
            "container_density_delta": 0.24,
        },
    )
    payment._cache["dup-run:satellite-logistics-intel"] = record
    calls = {"n": 0}

    def fake_purchase(**kwargs):
        calls["n"] += 1
        cached = payment._cache["dup-run:satellite-logistics-intel"]
        assert cached.state == payment.SUCCESS
        return cached

    monkeypatch.setattr(
        agent,
        "_fetch_json",
        lambda url, timeout=15.0: {
            "freshness_hours": 72,
            "quality_score": 0.62,
            "synthetic": True,
        },
    )
    monkeypatch.setattr(agent.payment, "purchase_premium", fake_purchase)
    first = run_research(
        question="Assess whether Port X is becoming congested.",
        budget_drops=5000,
        run_id="dup-run",
    )
    second = run_research(
        question="Assess whether Port X is becoming congested.",
        budget_drops=5000,
        run_id="dup-run",
    )
    assert first["transaction_hash"] == "ABC"
    assert second["transaction_hash"] == "ABC"
    assert first["final_confidence"] == 0.87
    assert calls["n"] == 2

