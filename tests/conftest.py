import pytest

from ledger402 import payment


@pytest.fixture(autouse=True)
def provider_bases(monkeypatch):
    monkeypatch.setenv("FREE_PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("PREMIUM_PROVIDER_URL", "http://localhost:8002")
    monkeypatch.setenv("TELEMETRY_PROVIDER_URL", "http://localhost:8003")
    monkeypatch.setenv("XRPL_WALLET_SEED", "sEdTestWalletSeedNotForSigning")
    monkeypatch.setenv("XRPL_PAY_TO", "rMerchantPayToAddressForTests")
    monkeypatch.setenv("XRPL_NETWORK", "xrpl:1")
    # The test suite must never reach an inference provider, and must exercise the
    # deterministic fallbacks that the demo depends on.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LEDGER402_TARGET_CONFIDENCE", raising=False)
    monkeypatch.delenv("LEDGER402_MAX_PURCHASES", raising=False)


@pytest.fixture(autouse=True)
def clean_payment_cache():
    """Process-local idempotency must not leak between tests."""
    payment.reset_cache()
    yield
    payment.reset_cache()


# Payloads the paid providers return, mirroring data/*.json.
SATELLITE_BODY = {
    "provider_id": "satellite-logistics-intel",
    "provider_name": "Satellite Logistics Intelligence",
    "port": "Port X",
    "container_density_delta": 0.24,
    "anchored_vessels_delta": 0.31,
    "yard_utilization": 0.91,
    "truck_activity_delta": 0.18,
    "freshness_hours": 3,
    "quality_score": 0.93,
    "synthetic": True,
}

TELEMETRY_BODY = {
    "provider_id": "terminal-ops-telemetry",
    "provider_name": "Terminal Operations Telemetry",
    "port": "Port X",
    "gate_turnaround_minutes": 84,
    "rail_dwell_hours": 41.5,
    "freshness_hours": 6,
    "quality_score": 0.81,
    "synthetic": True,
}

_BODY_FOR_PATH = {
    "/intelligence/port-congestion": (SATELLITE_BODY, "A" * 64),
    "/intelligence/terminal-operations": (TELEMETRY_BODY, "B" * 64),
}


@pytest.fixture
def settling_agent(monkeypatch):
    """Mock only the network and signing boundary.

    `purchase_premium`'s real control flow runs, including the audit events a live view
    depends on (HTTP_402_OBSERVED, negotiation, confirmation, unlock). Nothing is signed
    and no Testnet XRP is spent. Prefer this over mocking `purchase_premium` wholesale
    whenever a test cares about the event stream rather than only the outcome.
    """
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
