"""Audit trail and cryptographic proof anchoring.

Two jobs:

1. A timestamped event log that only ever claims states the agent can actually observe.
   The x402 client encapsulates submit-vs-validate, so the log records
   HTTP_402_OBSERVED / X402_PAYMENT_NEGOTIATION_STARTED / XRPL_PAYMENT_CONFIRMED and
   never invents intermediate ledger states.

2. The composite audit anchor from the deliverable spec:

       H_audit = SHA-256(dossier_summary || XOR(tx_hash_i) || timestamp)

   The XOR fold over settlement hashes is order-independent, so two runs that bought the
   same evidence in a different order anchor identically. A compliance auditor can
   recompute the anchor from the published report and verify each folded hash on the
   XRPL Testnet, establishing that the analysis came from paid feeds rather than from a
   hallucination.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable

# Width of an XRPL transaction hash in hex characters.
_TX_HASH_HEX_LEN = 64


def new_log() -> list[dict[str, Any]]:
    return []


def add(log: list[dict[str, Any]], event_type: str, **detail: Any) -> None:
    log.append(
        {
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "detail": detail,
        }
    )


def xor_fold_hashes(tx_hashes: Iterable[str]) -> str:
    """Order-independent fold of XRPL transaction hashes.

    Returns 64 zeros when the run settled nothing, which is itself meaningful: it marks a
    report that no on-ledger purchase backs.
    """
    accumulator = 0
    seen = False
    for tx_hash in tx_hashes:
        if not tx_hash:
            continue
        cleaned = str(tx_hash).strip().lower().removeprefix("0x")
        try:
            accumulator ^= int(cleaned, 16)
            seen = True
        except ValueError:
            # A non-hex hash is data we cannot fold; skip it rather than corrupt the anchor.
            continue
    if not seen:
        return "0" * _TX_HASH_HEX_LEN
    return format(accumulator, f"0{_TX_HASH_HEX_LEN}x").upper()


def compute_audit_anchor(
    *,
    dossier_summary: str,
    tx_hashes: Iterable[str],
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Compute H_audit and return it with everything needed to reproduce it."""
    hashes = [h for h in (tx_hashes or []) if h]
    folded = xor_fold_hashes(hashes)
    stamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")

    # The separator keeps the concatenation unambiguous: no summary can impersonate a
    # hash boundary and shift the fields.
    preimage = "\x1f".join([dossier_summary, folded, stamp])
    digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest().upper()

    return {
        "audit_hash": digest,
        "algorithm": "SHA-256",
        "folded_tx_hashes": folded,
        "settlement_count": len(hashes),
        "tx_hashes": list(hashes),
        "timestamp": stamp,
        "summary_length": len(dossier_summary),
        "verification": (
            "SHA-256 of dossier_summary, XOR-folded settlement hashes, and timestamp "
            "joined by US separator (0x1F). Each folded hash is independently "
            "verifiable on the XRPL Testnet."
        ),
    }


def verify_audit_anchor(anchor: dict[str, Any], dossier_summary: str) -> bool:
    """Recompute the anchor from a published report. Used by tests and auditors."""
    if not anchor:
        return False
    recomputed = compute_audit_anchor(
        dossier_summary=dossier_summary,
        tx_hashes=anchor.get("tx_hashes") or [],
        timestamp=anchor.get("timestamp"),
    )
    return recomputed["audit_hash"] == anchor.get("audit_hash")
