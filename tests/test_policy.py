from ledger402.policy import MAX_SINGLE_PURCHASE_DROPS, check

PREMIUM = {
    "id": "satellite_logistics_paid",
    "category": "port_congestion",
    "price_drops": 1200,
}


def test_policy_allows_default_purchase():
    result = check(PREMIUM, remaining_budget_drops=5000)
    assert result["allowed"] is True


def test_insufficient_budget():
    result = check(PREMIUM, remaining_budget_drops=500)
    assert result["allowed"] is False
    assert "budget" in result["reason"].lower()


def test_max_single_purchase():
    expensive = dict(PREMIUM, price_drops=MAX_SINGLE_PURCHASE_DROPS + 1)
    result = check(expensive, remaining_budget_drops=50000)
    assert result["allowed"] is False
    assert "max single purchase" in result["reason"].lower()


def test_disallowed_category():
    result = check(dict(PREMIUM, category="equities"), remaining_budget_drops=5000)
    assert result["allowed"] is False
