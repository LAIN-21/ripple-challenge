from ledger402.decision import UTILITY_THRESHOLD, evaluate_purchase, utility


FREE = {
    "freshness_hours": 72,
    "quality_score": 0.62,
}

PREMIUM = {
    "id": "satellite-logistics-intel",
    "name": "Satellite Logistics Intelligence",
    "category": "port_congestion",
    "price_drops": 1200,
    "freshness_hours": 3,
    "quality_score": 0.93,
    "expected_information_gain": 0.35,
}


def test_default_port_x_is_buy():
    result = evaluate_purchase(
        PREMIUM,
        current_confidence=0.58,
        current_evidence=FREE,
        remaining_budget_drops=5000,
    )
    assert result["decision"] == "BUY"
    assert result["utility"] >= UTILITY_THRESHOLD


def test_low_information_gain_is_skip():
    cheap = dict(PREMIUM, expected_information_gain=0.01)
    result = evaluate_purchase(
        cheap,
        current_confidence=0.58,
        current_evidence=FREE,
        remaining_budget_drops=5000,
    )
    assert result["decision"] == "SKIP"


def test_high_price_lowers_utility():
    expensive = dict(PREMIUM, price_drops=5000)
    high = utility(
        expected_information_gain=0.35,
        quality_score=0.93,
        freshness_hours=3,
        price_drops=5000,
        budget_drops=5000,
    )
    normal = utility(
        expected_information_gain=0.35,
        quality_score=0.93,
        freshness_hours=3,
        price_drops=1200,
        budget_drops=5000,
    )
    assert high < normal
    result = evaluate_purchase(
        expensive,
        current_confidence=0.58,
        current_evidence=FREE,
        remaining_budget_drops=5000,
    )
    assert result["decision"] == "SKIP"
