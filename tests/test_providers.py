from fastapi.testclient import TestClient

from apps.free_provider.main import app as free_app
from ledger402.providers import get_provider, providers_for_category, resolve_url


def test_category_filter():
    items = providers_for_category("port_congestion")
    assert {p["id"] for p in items} == {"public-port-stats", "satellite-logistics-intel"}


def test_resolve_url_uses_env_base_and_path():
    provider = get_provider("satellite-logistics-intel")
    url = resolve_url(provider, {"PREMIUM_PROVIDER_URL": "http://example.test:8002"})
    assert url == "http://example.test:8002/intelligence/port-congestion"


def test_free_provider_returns_synthetic_payload():
    client = TestClient(free_app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "free_provider"
    data = client.get("/intelligence/port-congestion")
    assert data.status_code == 200
    body = data.json()
    assert body["synthetic"] is True
    assert body["port"] == "Port X"


def test_premium_unpaid_returns_402(monkeypatch):
    monkeypatch.setenv("XRPL_PAY_TO", "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe")
    monkeypatch.setenv("XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai")
    monkeypatch.setenv("XRPL_PRICE_DROPS", "1200")
    monkeypatch.setenv("XRPL_NETWORK", "xrpl:1")
    from apps.premium_provider.main import create_app

    client = TestClient(create_app())
    unpaid = client.get("/intelligence/port-congestion")
    assert unpaid.status_code == 402
