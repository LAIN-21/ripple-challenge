"""Need-aware provider ranking.

The morning MVP scored a single provider against a fixed utility threshold. With one paid
option that was not a decision. Ranking here answers a different question:

    "Given what I already know and how certain I still need to be,
     which unpurchased provider buys me the most confidence per drop?"

Two providers with identical quality rank differently depending on what the agent already
holds: a feed whose signals are already covered has near-zero marginal gain and will not
be bought at any price. That is the property that makes the loop agentic rather than
scripted.

No LLM is involved. Every number here is reproducible and unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ledger402 import decision, policy
from ledger402.confidence import EvidenceItem, projected_confidence
from ledger402.tasks import TaskSpec

# A purchase must move the answer by at least this much to be worth settling on-ledger.
MIN_MARGINAL_GAIN = 0.02


@dataclass
class Candidate:
    """One paid provider evaluated against the current evidence set."""

    provider: dict[str, Any]
    marginal_gain: float
    projected_confidence: float
    price_drops: int
    efficiency: float
    utility: float
    eligible: bool
    reason: str
    policy_reason: str | None = None

    @property
    def provider_id(self) -> str:
        return str(self.provider.get("id") or "")

    @property
    def provider_name(self) -> str:
        return str(self.provider.get("name") or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "price_drops": self.price_drops,
            "marginal_confidence_gain": round(self.marginal_gain, 4),
            "projected_confidence": round(self.projected_confidence, 4),
            # Confidence points bought per 1000 drops, which is a readable unit in a UI.
            "confidence_per_1000_drops": round(self.efficiency * 1000, 4),
            "utility_prior": round(self.utility, 4),
            "eligible": self.eligible,
            "reason": self.reason,
        }


@dataclass
class Ranking:
    """The full comparison, kept whole so the UI can show what was rejected and why."""

    candidates: list[Candidate] = field(default_factory=list)

    @property
    def best(self) -> Candidate | None:
        eligible = [c for c in self.candidates if c.eligible]
        if not eligible:
            return None
        # Highest confidence per drop; ties broken by the cheaper purchase.
        return sorted(eligible, key=lambda c: (-c.efficiency, c.price_drops))[0]

    def to_list(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.candidates]


def evaluate_candidate(
    provider: dict[str, Any],
    *,
    evidence: Sequence[EvidenceItem],
    spec: TaskSpec,
    current_confidence: float,
    target_confidence: float,
    remaining_budget_drops: int,
    already_purchased: set[str],
    max_single_purchase_drops: int = policy.MAX_SINGLE_PURCHASE_DROPS,
) -> Candidate:
    """Score one provider. Cheap checks first so the reason is the most useful one."""
    price = int(provider.get("price_drops") or 0)
    provider_id = str(provider.get("id") or "")

    projected = projected_confidence(evidence, provider, spec)
    marginal = round(projected - current_confidence, 6)
    efficiency = (marginal / price) if price > 0 else 0.0

    # Retained from the morning MVP as an explainable quality prior, recorded in the
    # audit log. It no longer gates the purchase on its own.
    utility_prior = decision.utility(
        expected_information_gain=float(provider.get("expected_information_gain") or 0.0),
        quality_score=float(provider.get("quality_score") or 0.0),
        freshness_hours=float(provider.get("freshness_hours") or 0.0),
        price_drops=price,
        budget_drops=remaining_budget_drops,
    )

    def reject(reason: str, policy_reason: str | None = None) -> Candidate:
        return Candidate(
            provider=provider,
            marginal_gain=marginal,
            projected_confidence=projected,
            price_drops=price,
            efficiency=efficiency,
            utility=utility_prior,
            eligible=False,
            reason=reason,
            policy_reason=policy_reason,
        )

    if provider_id in already_purchased:
        return reject("Already purchased in this run.")

    if current_confidence >= target_confidence:
        return reject(
            f"Confidence {current_confidence:.0%} already meets the "
            f"{target_confidence:.0%} target; no further evidence needed."
        )

    if marginal < MIN_MARGINAL_GAIN:
        return reject(
            f"Would add only {marginal:.1%} confidence, below the "
            f"{MIN_MARGINAL_GAIN:.0%} minimum worth settling on-ledger."
        )

    verdict = policy.check(
        provider,
        remaining_budget_drops=remaining_budget_drops,
        max_single_purchase_drops=max_single_purchase_drops,
    )
    if not verdict["allowed"]:
        return reject(verdict["reason"], policy_reason=verdict["reason"])

    return Candidate(
        provider=provider,
        marginal_gain=marginal,
        projected_confidence=projected,
        price_drops=price,
        efficiency=efficiency,
        utility=utility_prior,
        eligible=True,
        reason=(
            f"Closes {marginal:.1%} of the confidence gap for {price} drops "
            f"({marginal / price * 1000:.2f} points per 1000 drops), "
            f"reaching {projected:.0%}."
        ),
    )


def rank_providers(
    providers: Sequence[dict[str, Any]],
    *,
    evidence: Sequence[EvidenceItem],
    spec: TaskSpec,
    current_confidence: float,
    target_confidence: float,
    remaining_budget_drops: int,
    already_purchased: set[str] | None = None,
    max_single_purchase_drops: int = policy.MAX_SINGLE_PURCHASE_DROPS,
) -> Ranking:
    """Rank every paid provider for the task. Free sources are fetched, not ranked."""
    purchased = already_purchased or set()
    candidates = [
        evaluate_candidate(
            provider,
            evidence=evidence,
            spec=spec,
            current_confidence=current_confidence,
            target_confidence=target_confidence,
            remaining_budget_drops=remaining_budget_drops,
            already_purchased=purchased,
            max_single_purchase_drops=max_single_purchase_drops,
        )
        for provider in providers
        if provider.get("payment_required")
    ]
    candidates.sort(key=lambda c: (not c.eligible, -c.efficiency))
    return Ranking(candidates=candidates)
