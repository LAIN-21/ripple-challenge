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
