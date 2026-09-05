"""Institutional Audit Invoice & Proof of Research generator.

Turns one procurement run into a compliance-grade, itemized settlement record a
private-bank auditor (Julius Baer / RegTech) can reconcile against the XRP Ledger
without trusting Ledger402's own bookkeeping: every line item carries the same
on-ledger transaction hash and Memo-embedded evidence proof committed at
procurement time (see `ledger402.payment.compute_evidence_hash`).

No spend, ranking, or confidence number here is recomputed — every figure is read
back from state the deterministic graph already produced.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from ledger402.payment import EXPLORER_TX, SUCCESS

DROPS_PER_XRP = 1_000_000

# Reference rate only, for a human-readable RLUSD-equivalent column. RLUSD is
# USD-pegged; this is not a live market quote and is never used to settle anything.
XRP_USD_REFERENCE_RATE = 0.55

NETWORK_FEE_DROPS_PER_TX = 10
PROTOCOL_TAKE_RATE = 0.025


def _xrp(drops: int) -> float:
    return round(drops / DROPS_PER_XRP, 6)


def _rlusd_equivalent(drops: int) -> float:
    return round(_xrp(drops) * XRP_USD_REFERENCE_RATE, 4)


def _client_address() -> str | None:
    seed = os.getenv("XRPL_WALLET_SEED")
    if not seed:
        return None
    try:
        from xrpl.wallet import Wallet

        return Wallet.from_seed(seed).classic_address
    except Exception:
        return None


def _confidence_gain_fraction(provider_id: str, rankings: list[dict[str, Any]]) -> float | None:
    """The marginal confidence gain ranking already computed for this purchase.

    Deterministic and unit-tested at the point of decision (ledger402.ranking); the
    invoice only looks it up, never recomputes it.
    """
    for entry in rankings:
        if entry.get("selected") != provider_id:
            continue
        for candidate in entry.get("candidates") or []:
            if candidate.get("provider_id") == provider_id:
                gain = candidate.get("marginal_confidence_gain")
                return float(gain) if gain is not None else None
    return None


def _line_item(
    purchase: dict[str, Any],
    *,
    catalog_by_id: dict[str, dict[str, Any]],
    rankings: list[dict[str, Any]],
) -> dict[str, Any]:
    provider_id = str(purchase.get("provider_id"))
    provider = catalog_by_id.get(provider_id, {})
    price_drops = int(purchase.get("price_drops") or 0)
    tx_hash = purchase.get("transaction_hash")
    gain = _confidence_gain_fraction(provider_id, rankings)

    return {
        "provider_id": provider_id,
        "vendor_name": purchase.get("provider_name") or provider.get("name") or provider_id,
        "seller_address": (
            provider.get("pay_to") or provider.get("curator_address") or os.getenv("XRPL_PAY_TO")
        ),
        "amount_paid": {
            "drops": price_drops,
            "xrp": _xrp(price_drops),
            "rlusd_equivalent": _rlusd_equivalent(price_drops),
        },
        "signals_acquired": list(provider.get("signals") or []),
        "confidence_gain": (
            f"+{gain * 100:.1f}% Confidence boost" if gain is not None else "n/a"
        ),
        "confidence_gain_fraction": gain,
        "tx_hash": tx_hash,
        "tx_explorer_url": EXPLORER_TX.format(hash=tx_hash) if tx_hash else None,
        "memo_proof": purchase.get("memo_proof"),
        "license": purchase.get("odrl") or provider.get("license"),
    }


def generate_procurement_invoice(state: dict[str, Any]) -> dict[str, Any]:
    """Build the itemized settlement record for one completed procurement run."""
    run_id = str(state.get("run_id") or "unknown")
    purchases = [p for p in (state.get("purchases") or []) if p.get("status") == SUCCESS]
    catalog_by_id = {str(p.get("id")): p for p in state.get("catalog") or []}
    rankings = state.get("rankings") or []

    line_items = [
        _line_item(purchase, catalog_by_id=catalog_by_id, rankings=rankings)
        for purchase in purchases
    ]

    total_drops = sum(item["amount_paid"]["drops"] for item in line_items)
    total_rlusd = round(sum(item["amount_paid"]["rlusd_equivalent"] for item in line_items), 4)
    network_fee_drops = NETWORK_FEE_DROPS_PER_TX * len(line_items)
    # Disclosed take-rate only: nothing in the settlement path collects this.
    protocol_fee_drops = int(round(total_drops * PROTOCOL_TAKE_RATE))

    audit_anchor = state.get("audit_anchor") or {}

    invoice: dict[str, Any] = {
        "invoice_id": f"INV-402-{run_id}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "agent_client_address": _client_address(),
        "line_items": line_items,
        "financial_summary": {
            "total_drops_spent": total_drops,
            "total_xrp_spent": _xrp(total_drops),
            "total_rlusd_volume": total_rlusd,
            "total_network_fee_drops": network_fee_drops,
            "protocol_take_rate": PROTOCOL_TAKE_RATE,
            "protocol_fee_drops": protocol_fee_drops,
            "protocol_fee_collected": False,
            "net_settlement_drops": total_drops + network_fee_drops,
            "initial_confidence": state.get("initial_confidence"),
            "final_confidence": state.get("confidence"),
            "composite_ledger_anchor_hash": audit_anchor.get("audit_hash"),
        },
    }
    invoice["markdown"] = _render_markdown(invoice)
    invoice["json"] = json.dumps(
        {k: v for k, v in invoice.items() if k != "json"}, indent=2, default=str
    )
    return invoice


def _license_label(license_value: Any) -> str:
    if isinstance(license_value, dict):
        return str(license_value.get("uid") or license_value.get("@type") or "ODRL Agreement")
    return str(license_value) if license_value else "—"


def _render_markdown(invoice: dict[str, Any]) -> str:
    lines = [
        f"# Institutional Procurement Invoice — {invoice['invoice_id']}",
        "",
        f"**Generated:** {invoice['generated_at']}  ",
        f"**Run ID:** `{invoice['run_id']}`  ",
        f"**Agent client address:** `{invoice.get('agent_client_address') or 'n/a'}`",
        "",
        "## Itemized accounting",
        "",
        "| Vendor | Seller address | Price (drops / RLUSD) | Signals acquired | "
        "Confidence gain | On-chain proof | License |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in invoice["line_items"]:
        amt = item["amount_paid"]
        tx = item.get("tx_hash")
        tx_cell = f"[{tx[:12]}…]({item['tx_explorer_url']})" if tx else "—"
        signals = ", ".join(item.get("signals_acquired") or []) or "—"
        lines.append(
            f"| {item['vendor_name']} | `{item.get('seller_address') or 'n/a'}` | "
            f"{amt['drops']} drops / ${amt['rlusd_equivalent']:.4f} | {signals} | "
            f"{item['confidence_gain']} | {tx_cell} | {_license_label(item.get('license'))} |"
        )

    summary = invoice["financial_summary"]
    lines += [
        "",
        "## Financial summary",
        "",
        f"- **Total drops spent:** {summary['total_drops_spent']} drops "
        f"({summary['total_xrp_spent']} XRP)",
        f"- **Total RLUSD volume (native DEX cross-currency settlement):** "
        f"${summary['total_rlusd_volume']:.4f}",
        f"- **XRPL network fees:** {summary['total_network_fee_drops']} drops",
        f"- **Ledger402 protocol take-rate (not collected on-ledger):** "
        f"{summary['protocol_take_rate']:.1%} ({summary['protocol_fee_drops']} drops)",
        f"- **Net settlement (data cost + network fee):** {summary['net_settlement_drops']} drops",
        f"- **Confidence:** {summary.get('initial_confidence') or 0:.0%} → "
        f"{summary.get('final_confidence') or 0:.1%}",
        f"- **Composite ledger anchor hash:** "
        f"`{summary.get('composite_ledger_anchor_hash') or 'n/a'}`",
    ]
    return "\n".join(lines)
