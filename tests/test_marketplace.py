"""B2C curator upload: 400-drop default, signal map, live catalog append."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger402 import marketplace, providers
from ledger402.tasks import CORE_SIGNAL_WEIGHTS, PORT_CONGESTION_SPEC
from server import app as gateway

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_b2c_customs.csv"


def test_sample_csv_latest_row_maps_to_advertised_signals():
    result = marketplace.register_b2c_dataset(
        SAMPLE, "Independent SGSIN curator", filename=str(SAMPLE)
    )
    assert result["price_drops"] == 400
    assert result["signals"] == ["customs_dwell", "chassis_availability", "inspection_backlog"]
    payload = result["provider"]["payload"]
    assert payload["customs_dwell"] == 31.2
    assert payload["chassis_availability"] == 0.42
    assert payload["inspection_backlog"] == 3400
    assert payload["port_code"] == "SGSIN"


def test_upload_appends_into_the_live_registry_and_catalog():
    client = TestClient(gateway)
    before = {p["id"] for p in client.get("/catalog").json()["providers"]}
    assert "public_port_stats" in before
    assert not any(pid.startswith("b2c_") for pid in before)

    response = client.post(
        "/api/b2c/upload",
        files={"file": ("sample_b2c_customs.csv", SAMPLE.read_bytes(), "text/csv")},
        data={"curator_label": "Dockside Analytics"},
    )
    assert response.status_code == 200
    body = response.json()
    dataset_id = body["dataset_id"]
    assert dataset_id.startswith("b2c_")
    assert body["price_drops"] == 400
    assert body["endpoint"] == f"/api/b2c/{dataset_id}"
    assert body["curator_address"]
    assert body["settlement_mode"] == "escrow"
    assert body["pay_to"] == "rMerchantPayToAddressForTests"

    catalog = {p["id"]: p for p in client.get("/catalog").json()["providers"]}
    assert dataset_id in catalog
    assert catalog[dataset_id]["price_drops"] == 400
    assert providers.get_provider(dataset_id) is not None


def test_b2c_route_is_gated_at_400_drops():
    client = TestClient(gateway)
    uploaded = client.post(
        "/api/b2c/upload",
        files={"file": ("sample_b2c_customs.csv", SAMPLE.read_bytes(), "text/csv")},
    )
    dataset_id = uploaded.json()["dataset_id"]
    unpaid = client.get(f"/api/b2c/{dataset_id}")
    assert unpaid.status_code == 402
    assert unpaid.headers.get("WWW-Authenticate") == "x402"
    assert unpaid.headers.get("x-payment-amount-drops") == "400"


def test_sample_csv_is_not_auto_registered():
    assert all(not str(p["id"]).startswith("b2c_") for p in providers.load_registry())


def test_core_b2b_weights_sum_to_one_and_b2c_weights_are_extra():
    assert sum(CORE_SIGNAL_WEIGHTS.values()) == 1.0
    extras = set(PORT_CONGESTION_SPEC.signal_weights) - set(CORE_SIGNAL_WEIGHTS)
    assert extras == {"customs_dwell", "chassis_availability", "inspection_backlog"}


def test_provision_always_escrows_to_xrpl_pay_to_and_discards_seed():
    wallet = marketplace.provision_curator_wallet()
    assert wallet["settlement_mode"] == "escrow"
    assert wallet["pay_to"] == "rMerchantPayToAddressForTests"
    assert wallet["curator_address"]
    assert wallet["seed"] is None


def test_provision_fails_closed_without_merchant(monkeypatch):
    monkeypatch.delenv("XRPL_PAY_TO", raising=False)
    with pytest.raises(ValueError, match="XRPL_PAY_TO"):
        marketplace.provision_curator_wallet()


def test_paid_b2c_get_credits_royalty_once(monkeypatch):
    import server as server_mod

    monkeypatch.setattr(server_mod, "_verify_tx_hash", lambda tx_hash, spec: True)
    client = TestClient(gateway)
    uploaded = client.post(
        "/api/b2c/upload",
        files={"file": ("sample_b2c_customs.csv", SAMPLE.read_bytes(), "text/csv")},
    )
    dataset_id = uploaded.json()["dataset_id"]
    unlocked = client.get(
        f"/api/b2c/{dataset_id}",
        headers={"x402-Tx-Hash": "C" * 64},
    )
    assert unlocked.status_code == 200
    rows = {row["dataset_id"]: row for row in client.get("/royalties").json()["royalties"]}
    assert rows[dataset_id]["accrued_drops"] == 400
    assert rows[dataset_id]["settlements"] == 1


def test_read_upload_rejects_bytes_over_the_cap():
    import asyncio

    from fastapi import HTTPException
    import server as server_mod

    class Fake:
        async def read(self, n):
            return b"x" * n

    with pytest.raises(HTTPException) as exc:
        asyncio.run(server_mod._read_upload(Fake(), 100))
    assert exc.value.status_code == 413


def test_faucet_failure_still_escrows_and_discards_seed(monkeypatch):
    monkeypatch.delenv("LEDGER402_SKIP_FAUCET", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def boom(*args, **kwargs):
        raise RuntimeError("faucet down")

    monkeypatch.setattr("xrpl.wallet.generate_faucet_wallet", boom)
    wallet = marketplace.provision_curator_wallet(timeout_seconds=0.1)
    assert wallet["settlement_mode"] == "escrow"
    assert wallet["pay_to"] == "rMerchantPayToAddressForTests"
    assert wallet["seed"] is None


def test_hung_faucet_returns_escrow_within_deadline(monkeypatch):
    import threading
    import time

    monkeypatch.delenv("LEDGER402_SKIP_FAUCET", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    released = threading.Event()

    def hang(*args, **kwargs):
        released.wait(timeout=5)

    monkeypatch.setattr("xrpl.wallet.generate_faucet_wallet", hang)
    started = time.monotonic()
    wallet = marketplace.provision_curator_wallet(timeout_seconds=0.2)
    elapsed = time.monotonic() - started
    released.set()
    assert elapsed < 1.5
    assert wallet["settlement_mode"] == "escrow"
    assert wallet["seed"] is None
