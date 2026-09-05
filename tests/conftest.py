import pytest

from ledger402 import marketplace, payment
from server import reset_consumed_hashes


@pytest.fixture(autouse=True)
def block_dotenv(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)


@pytest.fixture(autouse=True)
def provider_bases(monkeypatch):
    monkeypatch.setenv("PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("FREE_PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("PREMIUM_PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("TELEMETRY_PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("B2C_PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("XRPL_WALLET_SEED", "sEdTestWalletSeedNotForSigning")
    monkeypatch.setenv("XRPL_PAY_TO", "rMerchantPayToAddressForTests")
    monkeypatch.setenv("XRPL_NETWORK", "xrpl:1")
    monkeypatch.setenv("LEDGER402_SKIP_FAUCET", "1")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LEDGER402_TARGET_CONFIDENCE", raising=False)
    monkeypatch.delenv("LEDGER402_MAX_PURCHASES", raising=False)
    monkeypatch.delenv("LEDGER402_FUNDING_ASSET", raising=False)


@pytest.fixture(autouse=True)
def clean_payment_cache():
    payment.reset_cache()
    marketplace.reset()
    reset_consumed_hashes()
    yield
    payment.reset_cache()
    marketplace.reset()
    reset_consumed_hashes()


SATELLITE_BODY = {
    "provider_id": "satellite_logistics_paid",
    "provider_name": "Satellite Logistics Intelligence",
    "port": "Port of Singapore (PSA Multi-Terminal)",
    "port_code": "SGSIN",
    "container_density_delta": 0.94,
    "anchored_vessels_delta": 52,
    "yard_utilization": 0.89,
    "truck_activity_delta": 4.8,
    "freshness_hours": 3,
    "quality_score": 0.93,
    "synthetic": True,
}

TELEMETRY_BODY = {
    "provider_id": "terminal_telemetry_paid",
    "provider_name": "Terminal Operations Telemetry",
    "port": "Port of Singapore",
    "port_code": "SGSIN",
    "gate_turnaround_minutes": 41.5,
    "rail_dwell_hours": 0.92,
    "freshness_hours": 6,
    "quality_score": 0.81,
    "synthetic": True,
}

_BODY_FOR_PATH = {
    "/api/b2b/satellite-logistics": (SATELLITE_BODY, "A" * 64),
    "/api/b2b/terminal-telemetry": (TELEMETRY_BODY, "B" * 64),
    "/intelligence/port-congestion": (SATELLITE_BODY, "A" * 64),
    "/intelligence/terminal-operations": (TELEMETRY_BODY, "B" * 64),
}


@pytest.fixture
def settling_agent(monkeypatch):
    settled: list[str] = []

    def body_for(url: str):
        for path, pair in _BODY_FOR_PATH.items():
            if url.endswith(path):
                return pair
        raise AssertionError(f"unexpected provider url: {url}")

    class Unpaid:
        status_code = 402
        text = ""

    class Paid:
        def __init__(self, payload):
            self.status_code = 200
            self.content = b"{}"
            self.headers = {}
            self._payload = payload

        def json(self):
            return dict(self._payload)

    class Session:
        def get(self, url, timeout=None):
            payload, tx_hash = body_for(url)
            settled.append(tx_hash)
            self.last_hash = tx_hash
            return Paid(payload)

    session = Session()

    monkeypatch.setattr(payment, "observe_unpaid_402", lambda url, timeout=None: Unpaid())
    monkeypatch.setattr(payment, "_buyer_session", lambda **kwargs: session)
    monkeypatch.setattr(
        payment,
        "_decode_payment_header",
        lambda response: {"transaction": session.last_hash, "fee": 10},
    )
    return settled
