"""The institutional procurement invoice (deliverable spec, transparency pillar).

Every figure here must be a lookup against state the deterministic graph already
produced, never a recomputation — these tests pin that contract.
"""

from __future__ import annotations

from ledger402 import payment
from ledger402.invoice import generate_procurement_invoice

PROVIDER_A = {
    "id": "satellite_logistics_paid",
    "name": "Satellite Logistics Intelligence",
    "pay_to": "rMerchantAddressForTests",
    "signals": ["yard_utilization", "anchored_vessels_delta"],
    "price_drops": 1200,
    "license": "ODRL; AI_INFERENCE_COMMERCIAL_USE",
}

PROVIDER_B = {
    "id": "terminal_telemetry_paid",
    "name": "Terminal Operations Telemetry",
    "pay_to": "rMerchantAddressForTests",
    "signals": ["gate_turnaround_minutes"],
    "price_drops": 600,
    "license": "ODRL; EPHEMERAL_24H",
}

TX_A = "A" * 64
TX_B = "B" * 64


def _state():
    evidence_hash_a = payment.compute_evidence_hash(PROVIDER_A)
    evidence_hash_b = payment.compute_evidence_hash(PROVIDER_B)
    purchases = [
        {
            "provider_id": "satellite_logistics_paid",
            "provider_name": PROVIDER_A["name"],
            "price_drops": 1200,
            "status": payment.SUCCESS,
            "transaction_hash": TX_A,
            "memo_proof": evidence_hash_a,
        },
        {
            "provider_id": "terminal_telemetry_paid",
            "provider_name": PROVIDER_B["name"],
            "price_drops": 600,
            "status": payment.SUCCESS,
            "transaction_hash": TX_B,
            "memo_proof": evidence_hash_b,
        },
        {
            # A failed attempt must never appear on the invoice.
            "provider_id": "ghost_provider",
            "provider_name": "Ghost Provider",
            "price_drops": 999,
            "status": payment.FAILED,
        },
    ]
    rankings = [
        {
            "selected": "satellite_logistics_paid",
            "candidates": [
                {"provider_id": "satellite_logistics_paid", "marginal_confidence_gain": 0.29},
            ],
        },
        {
            "selected": "terminal_telemetry_paid",
            "candidates": [
                {"provider_id": "terminal_telemetry_paid", "marginal_confidence_gain": 0.047},
            ],
        },
    ]
    state = {
        "run_id": "test-run-1",
        "catalog": [PROVIDER_A, PROVIDER_B],
        "purchases": purchases,
        "rankings": rankings,
        "initial_confidence": 0.58,
        "confidence": 0.92,
        "audit_anchor": {"audit_hash": "F" * 64},
    }
    return state, evidence_hash_a, evidence_hash_b


def test_line_items_tally_to_total_drops_spent():
    state, _, _ = _state()
    invoice = generate_procurement_invoice(state)
    total = sum(item["amount_paid"]["drops"] for item in invoice["line_items"])
    assert total == 1800
    assert total == invoice["financial_summary"]["total_drops_spent"]


def test_failed_purchases_are_excluded_from_the_invoice():
    state, _, _ = _state()
    invoice = generate_procurement_invoice(state)
    ids = {item["provider_id"] for item in invoice["line_items"]}
    assert "ghost_provider" not in ids
    assert len(invoice["line_items"]) == 2


def test_transaction_links_match_the_xrpl_testnet_explorer_format():
    state, _, _ = _state()
    invoice = generate_procurement_invoice(state)
    for item in invoice["line_items"]:
        assert item["tx_hash"]
        assert (
            item["tx_explorer_url"]
            == f"https://testnet.xrpl.org/transactions/{item['tx_hash']}"
        )


def test_memo_proofs_match_the_sha256_evidence_hash():
    state, hash_a, hash_b = _state()
    invoice = generate_procurement_invoice(state)
    by_id = {item["provider_id"]: item for item in invoice["line_items"]}
    assert by_id["satellite_logistics_paid"]["memo_proof"] == hash_a
    assert by_id["terminal_telemetry_paid"]["memo_proof"] == hash_b
    # Independently recomputable from the same provider spec — no shared secret state.
    assert hash_a == payment.compute_evidence_hash(PROVIDER_A)
    assert len(hash_a) == 64


def test_confidence_gain_is_read_from_ranking_history_not_recomputed():
    state, _, _ = _state()
    invoice = generate_procurement_invoice(state)
    by_id = {item["provider_id"]: item for item in invoice["line_items"]}
    assert by_id["satellite_logistics_paid"]["confidence_gain"] == "+29.0% Confidence boost"
    assert by_id["terminal_telemetry_paid"]["confidence_gain"] == "+4.7% Confidence boost"


def test_financial_summary_includes_fees_and_anchor():
    state, _, _ = _state()
    invoice = generate_procurement_invoice(state)
    summary = invoice["financial_summary"]
    assert summary["total_network_fee_drops"] == 20  # 10 drops x 2 settlements
    assert summary["protocol_fee_drops"] == 45  # 2.5% of 1800, whole drops
    assert summary["protocol_fee_collected"] is False
    assert summary["net_settlement_drops"] == 1820  # data cost + network fee only
    assert summary["composite_ledger_anchor_hash"] == "F" * 64
    assert summary["final_confidence"] == 0.92


def test_exports_include_markdown_and_json():
    state, _, _ = _state()
    invoice = generate_procurement_invoice(state)
    assert invoice["invoice_id"] == "INV-402-test-run-1"
    assert "Institutional Procurement Invoice" in invoice["markdown"]
    assert "Satellite Logistics Intelligence" in invoice["markdown"]
    assert "not collected on-ledger" in invoice["markdown"]
    assert '"total_drops_spent": 1800' in invoice["json"]
    assert '"protocol_fee_drops": 45' in invoice["json"]
    assert '"net_settlement_drops": 1820' in invoice["json"]


def test_seller_address_falls_back_to_xrpl_pay_to(monkeypatch):
    state, _, _ = _state()
    for provider in state["catalog"]:
        provider.pop("pay_to", None)
    monkeypatch.setenv("XRPL_PAY_TO", "rFallbackMerchantAddressForInvoice")
    invoice = generate_procurement_invoice(state)
    assert all(
        item["seller_address"] == "rFallbackMerchantAddressForInvoice"
        for item in invoice["line_items"]
    )
