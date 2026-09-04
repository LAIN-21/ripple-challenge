from __future__ import annotations

from typing import Any


UTILITY_THRESHOLD = 0.50
INFO_GAIN_WEIGHT = 0.40
QUALITY_WEIGHT = 0.25
FRESHNESS_WEIGHT = 0.20
PRICE_WEIGHT = 0.15


def freshness_score(freshness_hours: float) -> float:
    return max(0.0, min(1.0, 1.0 - (float(freshness_hours) / 96.0)))


def normalized_price(price_drops: int, budget_drops: int) -> float:
    if budget_drops <= 0:
        return 1.0
    return min(1.0, price_drops / budget_drops)


def utility(
    *,
    expected_information_gain: float,
    quality_score: float,
    freshness_hours: float,
    price_drops: int,
    budget_drops: int,
) -> float:
    return (
        INFO_GAIN_WEIGHT * expected_information_gain
        + QUALITY_WEIGHT * quality_score
        + FRESHNESS_WEIGHT * freshness_score(freshness_hours)
        - PRICE_WEIGHT * normalized_price(price_drops, budget_drops)
    )


def improves_evidence(provider: dict[str, Any], current: dict[str, Any]) -> bool:
    return float(provider.get("freshness_hours", 99)) < float(
        current.get("freshness_hours", 99)
    ) or float(provider.get("quality_score", 0)) > float(current.get("quality_score", 0))


def evaluate_purchase(
    provider: dict[str, Any],
    *,
    current_confidence: float,
    current_evidence: dict[str, Any],
    remaining_budget_drops: int,
) -> dict[str, Any]:
    price = int(provider.get("price_drops") or 0)
    gain = float(provider.get("expected_information_gain") or 0)
    quality = float(provider.get("quality_score") or 0)
    hours = float(provider.get("freshness_hours") or 0)
    score = utility(
        expected_information_gain=gain,
        quality_score=quality,
        freshness_hours=hours,
        price_drops=price,
        budget_drops=remaining_budget_drops,
    )
    better = improves_evidence(provider, current_evidence)
    buy = score >= UTILITY_THRESHOLD and better
    reason = (
        f"Public evidence is {int(current_evidence.get('freshness_hours', 0))} hours old "
        f"and confidence is only {int(round(current_confidence * 100))}%. "
        f"The premium provider offers {int(hours)}-hour-old intelligence and the expected "
        f"information improvement justifies the {price} drop cost."
        if buy
        else (
            f"Utility {score:.2f} is below threshold {UTILITY_THRESHOLD:.2f} "
            "or the provider does not improve current evidence."
        )
    )
    return {
        "decision": "BUY" if buy else "SKIP",
        "provider": provider.get("name"),
        "provider_id": provider.get("id"),
        "price_drops": price,
        "utility": round(score, 4),
        "reason": reason,
    }
