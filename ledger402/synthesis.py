"""Analyst report generation, grounded in purchased evidence.

The LLM writes the answer from the evidence JSON the agent actually holds. It is told,
explicitly, that it has no other knowledge: an analyst report that cites a fact nobody
paid for is exactly the hallucination the audit anchor exists to rule out.

Without a key, a deterministic template reproduces the morning MVP's output, so the demo
never depends on inference being available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from ledger402 import llm
from ledger402.confidence import EvidenceItem

SYSTEM_PROMPT = """\
You are an institutional research analyst writing a short briefing for a decision maker.

Rules, in priority order:
1. Use ONLY the evidence JSON provided. You have no other knowledge about this subject.
2. Every quantitative claim must trace to a field in that JSON. Never invent signals.
3. If the evidence is insufficient for a firm conclusion, or the asked-about entity \
does not match the evidence (for example the question is about Port Klang but every \
payload is labeled SGSIN / Port of Singapore), return verdict "UNCLEAR / INSUFFICIENT_EVIDENCE".
4. State the confidence figure you are given. Do not invent your own.
5. No preamble, no sign-off, no markdown headers.

Return ONLY a JSON object:
{"verdict": "<HIGH | MODERATE | LOW congestion risk, or UNCLEAR / INSUFFICIENT_EVIDENCE>",
 "summary": "<2-3 sentences a decision maker can act on>",
 "evidence": ["<one bullet per material data point, each naming its source>"],
 "caveats": ["<limitations of the evidence held>"]}
"""

_FOREIGN_PORTS = (
    "klang",
    "rotterdam",
    "shanghai",
    "los angeles",
    "long beach",
    "hamburg",
    "busan",
    "ningbo",
)

_LOCAL_ALIASES = ("sgsin", "singapore", "psa")

# Verdict thresholds for the deterministic path, on yard utilization.
_HIGH_YARD_UTILIZATION = 0.85
_MODERATE_YARD_UTILIZATION = 0.70


@dataclass
class Report:
    verdict: str
    summary: str
    evidence: list[str]
    caveats: list[str]
    method: str  # "llm" or "template"
    synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "congestion_risk": self.verdict,
            "summary": self.summary,
            "evidence": self.evidence,
            "caveats": self.caveats,
            "method": self.method,
            "synthetic": self.synthetic,
        }

    def dossier_summary(self) -> str:
        """The canonical string fed into the audit anchor.

        Stable and order-independent so the anchor can be recomputed from the published
        report alone.
        """
        parts = [self.verdict, self.summary, *sorted(self.evidence)]
        return "\n".join(part.strip() for part in parts if part)


def _evidence_payload(evidence: Sequence[EvidenceItem]) -> list[dict[str, Any]]:
    return [
        {
            "provider": item.provider_name,
            "paid": item.paid,
            "price_drops": item.price_drops,
            "freshness_hours": item.freshness_hours,
            "quality_score": item.quality_score,
            "data": {
                key: value
                for key, value in item.payload.items()
                # Provider bookkeeping is noise for the analyst.
                if key not in {"provider_id", "provider_name", "synthetic"}
            },
        }
        for item in evidence
    ]


def _percent(value: Any) -> str | None:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return None


def _merged(evidence: Sequence[EvidenceItem]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in evidence:
        merged.update(item.payload)
    return merged


def synthesize_template(
    evidence: Sequence[EvidenceItem],
    *,
    confidence: float,
    subject: str,
) -> Report:
    """Deterministic report. Reproduces the morning MVP's output for the canonical run."""
    data = _merged(evidence)
    paid_items = [item for item in evidence if item.paid]

    yard = data.get("yard_utilization")
    try:
        yard_value = float(yard) if yard is not None else None
    except (TypeError, ValueError):
        yard_value = None

    if yard_value is None:
        verdict = "MODERATE / UNCLEAR"
    elif yard_value >= _HIGH_YARD_UTILIZATION:
        verdict = "HIGH"
    elif yard_value >= _MODERATE_YARD_UTILIZATION:
        verdict = "MODERATE"
    else:
        verdict = "LOW"

    bullets: list[str] = []
    for item in evidence:
        for key, label, formatter in (
            ("berth_occupancy", "Berth occupancy", _percent),
            ("vessel_queue", "Vessels queued", lambda v: f"{int(v)}"),
            ("average_wait_hours", "Average wait", lambda v: f"{float(v):.1f} h"),
            ("yard_utilization", "Yard utilization", _percent),
            ("anchored_vessels_delta", "Anchored vessels", lambda v: f"{int(v)}" if float(v) > 1.5 else f"+{_percent(v)}"),
            ("container_density_delta", "Container density", lambda v: _percent(v) if float(v) <= 1.5 else f"{float(v):.2f}"),
            ("truck_activity_delta", "Truck activity", lambda v: f"{float(v):.1f} h" if float(v) > 1.5 else f"+{_percent(v)}"),
            ("gate_turnaround_minutes", "Gate turnaround", lambda v: f"{float(v):.0f} min"),
            ("rail_dwell_hours", "Rail dwell", lambda v: f"{float(v):.1f} h"),
        ):
            if key not in item.payload:
                continue
            try:
                rendered = formatter(item.payload[key])
            except (TypeError, ValueError):
                continue
            if rendered:
                bullets.append(f"{label}: {rendered} ({item.provider_name})")

    if paid_items:
        summary = (
            f"{subject} shows {verdict.lower()} congestion risk. "
            f"Procured evidence from {len(paid_items)} paid source(s) resolves the "
            f"ambiguity left by stale public statistics, giving {confidence:.0%} confidence."
        )
    else:
        summary = (
            f"Public evidence on {subject} is stale and congestion is unclear from berth "
            f"and queue statistics alone. Confidence is {confidence:.0%}."
        )

    caveats = ["All provider data is synthetic; only x402 and XRPL settlement are real."]
    if not paid_items:
        caveats.append("No premium evidence was purchased for this run.")

    return Report(
        verdict=verdict,
        summary=summary,
        evidence=bullets,
        caveats=caveats,
        method="template",
    )


def _evidence_blob(evidence: Sequence[EvidenceItem]) -> str:
    parts: list[str] = []
    for item in evidence:
        payload = item.payload or {}
        for key in ("port_code", "port", "facility_name"):
            value = payload.get(key)
            if value:
                parts.append(str(value))
    return " ".join(parts).lower()


def entity_mismatch(subject: str, evidence: Sequence[EvidenceItem]) -> bool:
    """True when the question names a different port than the held payloads."""
    if not subject or not evidence:
        return False
    blob = _evidence_blob(evidence)
    if not blob:
        return False
    local = any(alias in blob for alias in _LOCAL_ALIASES)
    if not local:
        return False
    subj = subject.lower()
    if any(alias in subj for alias in _LOCAL_ALIASES):
        return False
    return any(name in subj for name in _FOREIGN_PORTS)


def _insufficient(subject: str) -> Report:
    return Report(
        verdict="UNCLEAR / INSUFFICIENT_EVIDENCE",
        summary=(
            f"Held evidence is labelled for a different entity than {subject}. "
            "No briefing is issued from unmatched payloads."
        ),
        evidence=[],
        caveats=["Evidence entity does not match the research question."],
        method="template",
    )


def synthesize(
    evidence: Sequence[EvidenceItem],
    *,
    question: str,
    confidence: float,
    subject: str,
) -> Report:
    """Write the report, preferring the LLM and falling back to the template."""
    if not evidence:
        return Report(
            verdict="UNCLEAR",
            summary="No evidence was available for this question.",
            evidence=[],
            caveats=["No provider returned data."],
            method="template",
        )

    if entity_mismatch(subject, evidence):
        return _insufficient(subject)

    fallback = synthesize_template(evidence, confidence=confidence, subject=subject)
    if not llm.is_enabled():
        return fallback

    user_prompt = (
        f"Question: {question}\n"
        f"Subject: {subject}\n"
        f"Measured confidence in the current evidence set: {confidence:.0%}\n\n"
        f"Evidence JSON:\n{json.dumps(_evidence_payload(evidence), indent=2)}"
    )
    try:
        parsed = llm.complete_json(SYSTEM_PROMPT, user_prompt)
    except llm.LLMUnavailable:
        return fallback

    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        # An empty body is worse than the template; keep the deterministic answer.
        return fallback

    def _string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(entry).strip() for entry in value if str(entry).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    caveats = _string_list(parsed.get("caveats"))
    synthetic_note = "All provider data is synthetic; only x402 and XRPL settlement are real."
    if synthetic_note not in caveats:
        caveats.append(synthetic_note)

    return Report(
        verdict=str(parsed.get("verdict") or fallback.verdict).strip(),
        summary=summary,
        evidence=_string_list(parsed.get("evidence")) or fallback.evidence,
        caveats=caveats,
        method="llm",
    )
