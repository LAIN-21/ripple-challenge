import pytest


@pytest.fixture(autouse=True)
def provider_bases(monkeypatch):
    monkeypatch.setenv("FREE_PROVIDER_URL", "http://localhost:8001")
    monkeypatch.setenv("PREMIUM_PROVIDER_URL", "http://localhost:8002")
    monkeypatch.setenv("XRPL_WALLET_SEED", "sEdTestWalletSeedNotForSigning")
    monkeypatch.setenv("XRPL_PAY_TO", "rMerchantPayToAddressForTests")
    monkeypatch.setenv("XRPL_NETWORK", "xrpl:1")
