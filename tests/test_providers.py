from fastapi.testclient import TestClient
import pytest

from apps.free_provider.main import app as free_app
from apps.paid_provider import create_paid_provider
from ledger402 import odrl
from ledger402.providers import get_provider, providers_for_category, resolve_url

SATELLITE_KWARGS = dict(
    service="premium_provider",
    title="test premium",
    path="/intelligence/port-congestion",
    provider_id="satellite-logistics-intel",
    data_file="premium_satellite_data.json",
    price_env="XRPL_PRICE_DROPS",
    default_price_drops="1200",
    description="Satellite logistics intelligence (synthetic)",
)

TELEMETRY_KWARGS = dict(
    service="telemetry_provider",
    title="test telemetry",
    path="/intelligence/terminal-operations",
    provider_id="terminal-ops-telemetry",
    data_file="terminal_telemetry_data.json",
    price_env="TELEMETRY_PRICE_DROPS",
    default_price_drops="600",
    description="Terminal operations telemetry (synthetic)",
)


@pytest.fixture
def merchant(monkeypatch):
    monkeypatch.setenv("XRPL_PAY_TO", "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe")
    monkeypatch.setenv("XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai")
    monkeypatch.setenv("XRPL_NETWORK", "xrpl:1")
    monkeypatch.setenv("XRPL_PRICE_DROPS", "1200")
    monkeypatch.setenv("TELEMETRY_PRICE_DROPS", "600")


def test_category_filter():
    items = providers_for_category("port_congestion")
    assert {p["id"] for p in items} == {
        "public-port-stats",
        "satellite-logistics-intel",
        "terminal-ops-telemetry",
    }


def test_registry_prices_match_the_env_defaults():
    """A price mismatch between registry and middleware makes every 402 unpayable."""
    assert get_provider("satellite-logistics-intel")["price_drops"] == 1200
    assert get_provider("terminal-ops-telemetry")["price_drops"] == 600


def test_registry_signals_are_declared_for_every_provider():
    """Ranking projects confidence from advertised signals; a missing list breaks it."""
    for provider in providers_for_category("port_congestion"):
        assert provider.get("signals"), f"{provider['id']} declares no signals"


def test_resolve_url_uses_env_base_and_path():
    provider = get_provider("satellite-logistics-intel")
    url = resolve_url(provider, {"PREMIUM_PROVIDER_URL": "http://example.test:8002"})
    assert url == "http://example.test:8002/intelligence/port-congestion"


def test_telemetry_resolve_url():
    provider = get_provider("terminal-ops-telemetry")
    url = resolve_url(provider, {"TELEMETRY_PROVIDER_URL": "http://example.test:8003"})
    assert url == "http://example.test:8003/intelligence/terminal-operations"


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


@pytest.mark.parametrize(
    "kwargs,path",
    [
        (SATELLITE_KWARGS, "/intelligence/port-congestion"),
        (TELEMETRY_KWARGS, "/intelligence/terminal-operations"),
    ],
)
def test_paid_providers_return_real_402_when_unpaid(merchant, kwargs, path):
    client = TestClient(create_paid_provider(**kwargs))
    assert client.get(path).status_code == 402


def test_paid_provider_requires_pay_to(monkeypatch):
    """Fail closed at startup: no payee means paid data would be served for free."""
    monkeypatch.delenv("XRPL_PAY_TO", raising=False)
    with pytest.raises(RuntimeError, match="XRPL_PAY_TO"):
        create_paid_provider(**SATELLITE_KWARGS)

    monkeypatch.setenv("XRPL_PAY_TO", "   ")
    with pytest.raises(RuntimeError, match="XRPL_PAY_TO"):
        create_paid_provider(**SATELLITE_KWARGS)


def test_paid_provider_health_is_not_gated(merchant):
    """Health must stay reachable so dev-start can report status without paying."""
    client = TestClient(create_paid_provider(**SATELLITE_KWARGS))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "premium_provider"


def test_odrl_agreement_shape():
    policy = odrl.agreement(
        provider_id="satellite-logistics-intel",
        dataset_id="satellite-logistics-intel",
        price_drops=1200,
    )
    assert policy["@context"] == odrl.ODRL_CONTEXT
    assert policy["@type"] == "Agreement"
    assert {p["action"] for p in policy["permission"]} == {"use", "derive"}
    # Redistribution must be prohibited: the buyer paid for use, not for resale.
    assert "distribute" in {p["action"] for p in policy["prohibition"]}
    assert policy["ledger402:settlement"]["price_drops"] == 1200


def test_odrl_compact_header_is_single_line():
    policy = odrl.agreement(
        provider_id="p", dataset_id="d", price_drops=600
    )
    compact = odrl.compact(policy)
    assert "\n" not in compact
    assert "permit=use,derive" in compact
    assert "prohibit=distribute,aggregate" in compact
