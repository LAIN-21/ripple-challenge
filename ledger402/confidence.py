"""Confidence from signal coverage.

The morning MVP hardcoded 58% before a purchase and 87% after it. That made the numbers
a script rather than a measurement, and an agent that cannot measure its own uncertainty
cannot decide whether to buy more evidence.

Here confidence is derived from the evidence the agent actually holds:

    credibility(source) = quality_score x max(0, 1 - freshness_hours / HORIZON)
    coverage            = sum over signals of weight(signal) x credibility(best source)
    confidence          = FLOOR + SPAN x coverage

FLOOR is the value of holding any evidence at all; SPAN scales the rest. Both constants
are calibrated so the canonical Port X scenario reproduces the documented demo figures
(public-only 58%, public + satellite 87%). This is an explainable heuristic, not a
statistical model, and the UI says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ledger402.tasks import FRESHNESS_HORIZON_HOURS, TaskSpec, signals_in

# Calibrated against the canonical Port X scenario. See AGENT_PLAN.md.
CONFIDENCE_FLOOR = 0.56
CONFIDENCE_SPAN = 0.511

# A confidence ceiling: synthetic evidence never justifies certainty.
CONFIDENCE_CEILING = 0.97


@dataclass(frozen=True)
class EvidenceItem:
    """One payload the agent holds, with the provider metadata it came from."""

    provider_id: str
    provider_name: str
    payload: dict[str, Any]
    paid: bool = False
    price_drops: int = 0

    @property
    def quality_score(self) -> float:
        return float(self.payload.get("quality_score") or 0.0)

    @property
    def freshness_hours(self) -> float:
        return float(self.payload.get("freshness_hours") or 0.0)

    @property
    def credibility(self) -> float:
        return credibility(self.quality_score, self.freshness_hours)


def credibility(quality_score: float, freshness_hours: float) -> float:
    """How much a source's signals can be trusted: quality decayed by staleness."""
    freshness = max(0.0, 1.0 - (float(freshness_hours) / FRESHNESS_HORIZON_HOURS))
    return max(0.0, min(1.0, float(quality_score))) * freshness


def coverage(evidence: Iterable[EvidenceItem], spec: TaskSpec) -> dict[str, float]:
    """Best credibility obtained for each signal across all held evidence."""
    best: dict[str, float] = {}
    for item in evidence:
        item_credibility = item.credibility
        for signal in signals_in(item.payload, spec):
            if item_credibility > best.get(signal, 0.0):
                best[signal] = item_credibility
    return best


def coverage_score(evidence: Iterable[EvidenceItem], spec: TaskSpec) -> float:
    per_signal = coverage(evidence, spec)
    return sum(spec.weight(signal) * value for signal, value in per_signal.items())


def confidence(evidence: Iterable[EvidenceItem], spec: TaskSpec) -> float:
    """Confidence in the current answer, in [FLOOR, CONFIDENCE_CEILING]."""
    items = list(evidence)
    if not items:
        return 0.0
    score = CONFIDENCE_FLOOR + CONFIDENCE_SPAN * coverage_score(items, spec)
    return round(min(CONFIDENCE_CEILING, score), 4)


def projected_confidence(
    evidence: Iterable[EvidenceItem],
    provider: dict[str, Any],
    spec: TaskSpec,
) -> float:
    """Confidence the agent would reach if it bought `provider`.

    Uses the provider's *advertised* signals and quality, because before paying that is
    all the agent knows. After the purchase, `confidence()` re-measures against what was
    actually delivered, so an over-promising provider does not keep the credit.
    """
    advertised = {
        "quality_score": float(provider.get("quality_score") or 0.0),
        "freshness_hours": float(provider.get("freshness_hours") or 0.0),
    }
    # Advertised signals are declared in the registry as a list of names.
    for signal in provider.get("signals") or []:
        advertised.setdefault(str(signal), 1.0)

    hypothetical = EvidenceItem(
        provider_id=str(provider.get("id") or "candidate"),
        provider_name=str(provider.get("name") or "candidate"),
        payload=advertised,
        paid=bool(provider.get("payment_required")),
        price_drops=int(provider.get("price_drops") or 0),
    )
    return confidence([*evidence, hypothetical], spec)


def uncertainty_gap(current: float, target: float) -> float:
    """How far the answer still is from the confidence the objective asked for."""
    return max(0.0, round(float(target) - float(current), 4))
