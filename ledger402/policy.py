from __future__ import annotations

from typing import Any

ALLOWED_CATEGORIES = frozenset({"port_congestion"})
MAX_SINGLE_PURCHASE_DROPS = 2000


def check(
    provider: dict[str, Any],
    *,
    remaining_budget_drops: int,
    max_single_purchase_drops: int = MAX_SINGLE_PURCHASE_DROPS,
) -> dict[str, Any]:
    price = int(provider.get("price_drops") or 0)
    category = str(provider.get("category") or "")
    if category not in ALLOWED_CATEGORIES:
        return {
            "allowed": False,
            "reason": f"Category {category!r} is not allowed.",
        }
    if price > remaining_budget_drops:
        return {
            "allowed": False,
            "reason": f"Price {price} drops exceeds remaining procurement budget {remaining_budget_drops} drops.",
        }
    if price > max_single_purchase_drops:
        return {
            "allowed": False,
            "reason": f"Price {price} drops exceeds max single purchase {max_single_purchase_drops} drops.",
        }
    return {"allowed": True, "reason": "Spending policy approved."}
