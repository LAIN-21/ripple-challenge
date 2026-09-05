from fastapi.testclient import TestClient
import pytest

from ledger402 import odrl
from ledger402.providers import get_provider, providers_for_category, resolve_url
from server import app as gateway


def test_category_filter():
    items = providers_for_category("port_congestion")
    assert {p["id"] for p in items} == {
        "public_port_stats",
        "satellite_logistics_paid",
        "terminal_telemetry_paid",
    }


def test_registry_prices_match_the_env_defaults():
    assert get_provider("satellite_logistics_paid")["price_drops"] == 1200
    assert get_provider("terminal_telemetry_paid")["price_drops"] == 600


def test_registry_signals_are_declared_for_every_provider():
    for provider in providers_for_category("port_congestion"):
        assert provider.get("signals"), f"{provider['id']} declares no signals"


def test_resolve_url_uses_env_base_and_path():
    provider = get_provider("satellite_logistics_paid")
    url = resolve_url(provider, {"PREMIUM_PROVIDER_URL": "http://example.test:8001"})
    assert url == "http://example.test:8001/api/b2b/satellite-logistics"


def test_telemetry_resolve_url():
    provider = get_provider("terminal_telemetry_paid")
    url = resolve_url(provider, {"TELEMETRY_PROVIDER_URL": "http://example.test:8001"})
    assert url == "http://example.test:8001/api/b2b/terminal-telemetry"


def test_free_provider_returns_synthetic_payload():
    client = TestClient(gateway)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "provider_gateway"
    data = client.get("/api/b2b/public-stats")
    assert data.status_code == 200
    body = data.json()
    assert body["synthetic"] is True
    assert body["port_code"] == "SGSIN"
    assert "berth_occupancy" in body


@pytest.mark.parametrize(
    "path",
    ["/api/b2b/satellite-logistics", "/api/b2b/terminal-telemetry"],
)
def test_paid_providers_return_real_402_when_unpaid(path):
    client = TestClient(gateway)
    response = client.get(path)
    assert response.status_code == 402
    assert response.headers.get("WWW-Authenticate") == "x402"
    assert response.headers.get("x-payment-protocol") == "x402-xrpl"
    assert response.headers.get("x-payment-network") == "xrpl:1"
    assert response.headers.get("x-payment-amount-drops") in {"1200", "600"}
    assert response.headers.get("x-payment-destination")
    assert response.headers.get("x-machine-license") == "ODRL; Commercial_Derivative_Permitted"


def test_paid_provider_health_is_not_gated():
    client = TestClient(gateway)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "provider_gateway"


def test_odrl_agreement_shape():
    policy = odrl.agreement(
        provider_id="satellite_logistics_paid",
        dataset_id="satellite_logistics_paid",
        price_drops=1200,
    )
    assert policy["@context"] == odrl.ODRL_CONTEXT
    assert policy["@type"] == "Agreement"
    assert {p["action"] for p in policy["permission"]} == {"use", "derive"}
    assert "distribute" in {p["action"] for p in policy["prohibition"]}
    assert policy["ledger402:settlement"]["price_drops"] == 1200


def test_recorded_tx_hash_header_unlocks_when_verified(monkeypatch):
    import server as server_mod

    monkeypatch.setattr(server_mod, "_verify_tx_hash", lambda tx_hash, spec: True)
    client = TestClient(gateway)
    response = client.get(
        "/api/b2b/satellite-logistics",
        headers={"x402-Tx-Hash": "F" * 64},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["port_code"] == "SGSIN"
    assert "yard_utilization" in body


def test_payment_signature_header_unlocks_when_verified(monkeypatch):
    import server as server_mod

    monkeypatch.setattr(server_mod, "_verify_tx_hash", lambda tx_hash, spec: True)
    client = TestClient(gateway)
    response = client.get(
        "/api/b2b/terminal-telemetry",
        headers={"PAYMENT-SIGNATURE": "A" * 64},
    )
    assert response.status_code == 200
    assert "gate_turnaround_minutes" in response.json()


def test_unverified_tx_hash_header_does_not_unlock(monkeypatch):
    import server as server_mod

    monkeypatch.setattr(server_mod, "_verify_tx_hash", lambda tx_hash, spec: False)
    client = TestClient(gateway)
    response = client.get(
        "/api/b2b/satellite-logistics",
        headers={"x402-Tx-Hash": "F" * 64},
    )
    assert response.status_code == 402


def test_odrl_compact_header_is_single_line():
    policy = odrl.agreement(provider_id="p", dataset_id="d", price_drops=600)
    compact = odrl.compact(policy)
    assert "\n" not in compact
    assert "permit=use,derive" in compact
    assert "prohibit=distribute,aggregate" in compact
