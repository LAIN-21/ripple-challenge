"""LEDGER402_FUNDING_ASSET must fail closed on typos, not silently pay in XRP."""

from __future__ import annotations

import pytest

from ledger402.payment import normalize_funding_asset
from server import _funding_asset, _gate_for


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, "XRP"),
        ("", "XRP"),
        ("   ", "XRP"),
        ("xrp", "XRP"),
        ("RLUSD", "RLUSD"),
        ("rlusd", "RLUSD"),
    ],
)
def test_normalize_funding_asset_accepts_blank_xrp_and_rlusd(raw, expected):
    assert normalize_funding_asset(raw) == expected


@pytest.mark.parametrize("raw", ["RLUSDD", "RLUSC", "USD", "BTC"])
def test_normalize_funding_asset_rejects_typos(raw):
    with pytest.raises(ValueError, match="Unsupported LEDGER402_FUNDING_ASSET"):
        normalize_funding_asset(raw)


def test_blank_env_defaults_to_xrp(monkeypatch):
    monkeypatch.delenv("LEDGER402_FUNDING_ASSET", raising=False)
    assert normalize_funding_asset() == "XRP"
    assert _funding_asset() == "XRP"


def test_invalid_env_fails_before_gate(monkeypatch):
    monkeypatch.setenv("LEDGER402_FUNDING_ASSET", "RLUSDD")
    with pytest.raises(ValueError, match="RLUSDD"):
        _funding_asset()
    with pytest.raises(ValueError, match="Unsupported"):
        _gate_for(
            "/api/b2b/satellite-logistics",
            {"price_drops": 1200, "pay_to": "rMerchantPayToAddressForTests"},
        )
