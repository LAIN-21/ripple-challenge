"""Tier 1 narrative vs Tier 2 rectangular bundle, and entity-mismatch UNCLEAR."""

from __future__ import annotations

from ledger402 import bundle, graph, payment, synthesis
from tests.test_confidence import FREE, SATELLITE
from tests.test_graph import (  # noqa: F401 - fixtures
    QUESTION,
    free_provider_up,
    paying_agent,
)


def test_entity_mismatch_returns_unclear_without_calling_the_llm(monkeypatch):
    from ledger402 import llm

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        llm, "complete_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not run"))
    )
    report = synthesis.synthesize(
        [FREE, SATELLITE],
        question="Is Port Klang facing critical yard congestion?",
        confidence=0.87,
        subject="Port Klang",
    )
    assert report.verdict == "UNCLEAR / INSUFFICIENT_EVIDENCE"
    assert report.method == "template"


def test_matching_sgsin_subject_is_not_an_entity_mismatch():
    assert not synthesis.entity_mismatch("Port of Singapore (PSA)", [FREE, SATELLITE])
    assert synthesis.entity_mismatch("Port Klang", [FREE, SATELLITE])


def test_port_of_los_angeles_with_sgsin_evidence_is_unclear():
    report = synthesis.synthesize(
        [FREE, SATELLITE],
        question="Is Port of Los Angeles facing critical yard congestion?",
        confidence=0.87,
        subject="Port of Los Angeles",
    )
    assert report.verdict == "UNCLEAR / INSUFFICIENT_EVIDENCE"
    assert report.method == "template"


def test_tier_1_returns_a_report_not_a_table(paying_agent):  # noqa: F811
    result = graph.run_agent(
        question=QUESTION,
        budget_drops=5000,
        target_confidence=0.85,
        delivery_tier="tier_1",
    )
    assert result["delivery_tier"] == "tier_1"
    assert result["report"]["method"] == "template"
    assert result.get("data_bundle") is None
    assert result["report"]["congestion_risk"] != "DATA_BUNDLE"


def test_tier_2_returns_normalized_rows_and_skips_narrative(paying_agent):  # noqa: F811
    result = graph.run_agent(
        question=QUESTION,
        budget_drops=5000,
        target_confidence=0.85,
        delivery_tier="tier_2",
    )
    assert result["delivery_tier"] == "tier_2"
    built = result["data_bundle"]
    assert built["tier"] == "tier_2"
    assert "75% discount" in built["discount"]
    assert built["records"]
    assert "provider_id" in built["records"][0]
    assert "price_drops" in built["records"][0]
    assert built["csv"].startswith("provider_id")
    assert result["report"]["method"] == "bundle"
    assert result["audit_anchor"]["audit_hash"]
    # Product SKU copy only — x402 prices stay 1200.
    assert result["spent_drops"] == 1200


def test_bundle_join_carries_tx_hash_and_integrity_digest():
    purchases = [
        {
            "provider_id": SATELLITE.provider_id,
            "provider_name": SATELLITE.provider_name,
            "price_drops": 1200,
            "transaction_hash": "A" * 64,
            "explorer_url": "https://testnet.xrpl.org/transactions/" + "A" * 64,
            "status": payment.SUCCESS,
        }
    ]
    built = bundle.build_bundle(
        [FREE, SATELLITE],
        purchases=purchases,
        question=QUESTION,
        subject="Port X",
        confidence=0.87,
    )
    satellite_row = next(r for r in built["records"] if r["provider_id"] == SATELLITE.provider_id)
    assert satellite_row["tx_hash"] == "A" * 64
    assert satellite_row["paid"] is True
    assert satellite_row["yard_utilization"] == 0.91
    assert len(built["integrity_hash"]) == 64
    assert built["odrl"]["permission"]
    assert any(p.get("action") == "derive" for p in built["odrl"]["permission"])
    assert built["json"]
    assert built["csv"]
    parquet = built.get("parquet")
    assert parquet is None or isinstance(parquet, str)


def test_parquet_bytes_are_base64_encoded(monkeypatch):
    monkeypatch.setattr(bundle, "_to_parquet", lambda records: b"\x00\x01")
    built = bundle.build_bundle(
        [FREE, SATELLITE],
        purchases=[],
        question=QUESTION,
        subject="Port X",
        confidence=0.87,
    )
    assert built["parquet"] == "AAE="
    assert built["json"]
    assert built["csv"]


def test_parquet_write_failure_still_returns_json_and_csv(monkeypatch):
    monkeypatch.setattr(bundle, "_to_parquet", lambda records: None)
    built = bundle.build_bundle(
        [FREE, SATELLITE],
        purchases=[],
        question=QUESTION,
        subject="Port X",
        confidence=0.87,
    )
    assert "parquet" not in built
    assert built["json"]
    assert built["csv"].startswith("provider_id")


def test_to_parquet_returns_none_when_rows_cannot_be_written():
    assert bundle._to_parquet([{"nested": object()}]) is None
