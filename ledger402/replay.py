"""Offline replay of a recorded Testnet two-settlement run."""

from __future__ import annotations

from typing import Any

from providers_data import OFFLINE_REPLAY_SETTLEMENTS, PROVIDERS_REGISTRY

from ledger402 import odrl
from ledger402.payment import EXPLORER_TX, SUCCESS, compute_evidence_hash
from ledger402.providers import flatten_payload


def settlement_for(provider_id: str, *, target_confidence: float, index: int) -> dict[str, Any]:
    """Pick the recorded hash for this purchase in a replayed run."""
    if target_confidence >= 0.90:
        if index not in (0, 1):
            raise ValueError(
                "Canonical 0.92 replay only has two recorded settlements; "
                f"index {index} would reuse a hash."
            )
        canonical = OFFLINE_REPLAY_SETTLEMENTS["canonical_target_92"]
        tx = canonical["tx_1"] if index == 0 else canonical["tx_2"]
        amount = 1200 if index == 0 else 600
        return {"tx_hash": tx, "amount_drops": amount, "result": "tesSUCCESS"}
    recorded = OFFLINE_REPLAY_SETTLEMENTS.get(provider_id) or {}
    return {
        "tx_hash": recorded.get("tx_hash"),
        "amount_drops": recorded.get("amount_drops"),
        "ledger_index": recorded.get("ledger_index"),
        "result": recorded.get("result", "tesSUCCESS"),
    }


def recorded_payload(provider_id: str) -> dict[str, Any]:
    if provider_id in PROVIDERS_REGISTRY:
        return flatten_payload(provider_id)
    spec = PROVIDERS_REGISTRY.get(provider_id)
    if spec:
        return flatten_payload(provider_id, spec)
    raise KeyError(provider_id)


def replay_purchase(provider: dict[str, Any], *, index: int, target_confidence: float) -> dict[str, Any]:
    provider_id = str(provider.get("id"))
    price = int(provider.get("price_drops") or 0)
    settled = settlement_for(provider_id, target_confidence=target_confidence, index=index)
    tx = str(settled.get("tx_hash") or "")
    body = recorded_payload(provider_id)
    body["odrl"] = odrl.agreement(
        provider_id=provider_id,
        dataset_id=provider_id,
        price_drops=price,
        purpose="commercialDerivative",
    )
    return {
        "state": SUCCESS,
        "tx_hash": tx,
        "body": body,
        "explorer_url": EXPLORER_TX.format(hash=tx) if tx else None,
        "ledger_index": settled.get("ledger_index"),
        "price_drops": price,
        # A live run embeds this hash as the Memo bound to the settling Payment
        # (payment.compute_evidence_hash); replay recomputes it from the same
        # provider spec so a recorded receipt carries a realistic audit proof.
        "memo_proof": compute_evidence_hash(provider),
    }
