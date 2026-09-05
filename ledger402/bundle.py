"""Tier 2: join, normalize, hash, and attach receipts — no narrative LLM."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any, Sequence

from ledger402.confidence import EvidenceItem
from ledger402 import odrl

TIER_2_DISCOUNT_NOTE = "Raw verified data bundle priced at a 75% discount versus the advisory dossier."


def _flat_row(item: EvidenceItem, *, tx_hash: str | None) -> dict[str, Any]:
    payload = dict(item.payload or {})
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    row: dict[str, Any] = {
        "provider_id": item.provider_id,
        "provider_name": item.provider_name,
        "paid": item.paid,
        "price_drops": item.price_drops,
        "tx_hash": tx_hash,
        "port_code": payload.get("port_code") or payload.get("port"),
        "freshness_hours": item.freshness_hours,
        "quality_score": item.quality_score,
    }
    for key, value in {**metrics, **payload}.items():
        if key in {"metrics", "rows", "odrl", "signals_provided", "anchorage_hotspots", "terminal_ids"}:
            continue
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            row.setdefault(key, value)
    return row


def _tx_for(item: EvidenceItem, purchases: Sequence[dict[str, Any]]) -> str | None:
    for purchase in purchases:
        if purchase.get("provider_id") == item.provider_id and purchase.get("transaction_hash"):
            return str(purchase["transaction_hash"])
    return None


def canonical_json(records: Sequence[dict[str, Any]]) -> str:
    return json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)


def integrity_hash(records: Sequence[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(records).encode("utf-8")).hexdigest()


def _to_parquet(records: Sequence[dict[str, Any]]) -> bytes | None:
    """Optional Parquet export. Missing pyarrow must not break JSON/CSV delivery."""
    if not records:
        return None
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None
    table = pa.Table.from_pylist([dict(row) for row in records])
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def to_csv(records: Sequence[dict[str, Any]]) -> str:
    if not records:
        return ""
    keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key, "") for key in keys})
    return buf.getvalue()


def build_bundle(
    evidence: Sequence[EvidenceItem],
    *,
    purchases: Sequence[dict[str, Any]] | None = None,
    question: str = "",
    subject: str = "",
    confidence: float = 0.0,
) -> dict[str, Any]:
    buys = list(purchases or [])
    records = [_flat_row(item, tx_hash=_tx_for(item, buys)) for item in evidence]
    receipts = [
        {
            "provider_id": p.get("provider_id"),
            "provider_name": p.get("provider_name"),
            "price_drops": p.get("price_drops"),
            "transaction_hash": p.get("transaction_hash"),
            "explorer_url": p.get("explorer_url"),
            "status": p.get("status"),
            "odrl": p.get("odrl"),
        }
        for p in buys
        if p.get("status") == "SUCCESS"
    ]
    policy = odrl.agreement(
        provider_id="ledger402-bundle",
        dataset_id="verified-data-bundle",
        price_drops=sum(int(p.get("price_drops") or 0) for p in receipts),
        purpose="commercialDerivative",
    )
    digest = integrity_hash(records)
    bundle = {
        "tier": "tier_2",
        "product": "Raw Verified Data Bundle",
        "discount": TIER_2_DISCOUNT_NOTE,
        "question": question,
        "subject": subject,
        "confidence": confidence,
        "records": records,
        "csv": to_csv(records),
        "json": json.dumps(records, indent=2, default=str),
        "integrity_hash": digest,
        "receipts": receipts,
        "odrl": policy,
        "synthetic": True,
    }
    parquet = _to_parquet(records)
    if parquet is not None:
        bundle["parquet"] = parquet
    return bundle
