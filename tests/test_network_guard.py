"""The network safety rail: this build must never sign against Mainnet by accident."""

from __future__ import annotations

import pytest

from ledger402 import network, payment

MAINNET_RPC = "https://s1.ripple.com:51234/"
TESTNET_RPC = "https://s.altnet.rippletest.net:51234/"


def test_testnet_configuration_is_accepted():
    network.assert_testnet(TESTNET_RPC, "xrpl:1")
    network.assert_testnet("https://s.devnet.rippletest.net:51234/", "xrpl:2")


@pytest.mark.parametrize(
    "rpc,net",
    [
        (MAINNET_RPC, "xrpl:1"),          # Mainnet host with a testnet id
        (TESTNET_RPC, "xrpl:0"),          # testnet host with the Mainnet id
        (MAINNET_RPC, "xrpl:0"),          # both wrong
        ("https://xrplcluster.com/", "xrpl:1"),
    ],
)
def test_non_testnet_configuration_is_refused(rpc, net):
    with pytest.raises(network.NonTestnetBlocked):
        network.assert_testnet(rpc, net)


def test_refusal_names_the_offending_setting():
    """The operator must be able to tell which of the two values is wrong."""
    with pytest.raises(network.NonTestnetBlocked, match="RPC host"):
        network.assert_testnet(MAINNET_RPC, "xrpl:1")
    with pytest.raises(network.NonTestnetBlocked, match="network id"):
        network.assert_testnet(TESTNET_RPC, "xrpl:0")


def test_unknown_host_is_refused_not_allowed():
    """Allowlist, not blocklist: an unrecognised endpoint must fail closed."""
    with pytest.raises(network.NonTestnetBlocked):
        network.assert_testnet("https://some-new-rpc.example.com/", "xrpl:1")


def test_explicit_override_permits_other_networks(monkeypatch):
    """A guard nobody can disable gets deleted; the opt-in is loud and documented."""
    monkeypatch.setenv(network.ALLOW_OVERRIDE_ENV, "1")
    network.assert_testnet(MAINNET_RPC, "xrpl:0")


def test_override_ignores_unrelated_values(monkeypatch):
    monkeypatch.setenv(network.ALLOW_OVERRIDE_ENV, "maybe")
    with pytest.raises(network.NonTestnetBlocked):
        network.assert_testnet(MAINNET_RPC, "xrpl:0")


def test_purchase_reports_a_blocked_network_as_config_error_not_unknown(monkeypatch):
    """UNKNOWN means a transaction may be in flight. Nothing was signed here."""
    monkeypatch.setenv("XRPL_RPC_URL", MAINNET_RPC)

    class Fake402:
        status_code = 402
        text = ""

    monkeypatch.setattr(payment, "observe_unpaid_402", lambda url, timeout=None: Fake402())

    record = payment.purchase_premium(
        url="http://localhost:8002/intelligence/port-congestion",
        run_id="guard-run",
        provider_id="satellite-logistics-intel",
        expected_drops=1200,
        remaining_budget_drops=5000,
    )
    assert record.state == payment.CONFIG_ERROR
    assert record.tx_hash is None
    assert "test networks only" in record.error


def test_status_reports_the_current_posture(monkeypatch):
    monkeypatch.setenv("XRPL_RPC_URL", TESTNET_RPC)
    monkeypatch.setenv("XRPL_NETWORK", "xrpl:1")
    status = network.current_status()
    assert status["is_testnet"] is True
    assert status["override_enabled"] is False

    monkeypatch.setenv("XRPL_RPC_URL", MAINNET_RPC)
    assert network.current_status()["is_testnet"] is False
