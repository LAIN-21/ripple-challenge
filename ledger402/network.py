"""Network safety rail: this build settles on XRPL test networks only.

Every amount in this project is denominated in drops and every provider is synthetic, so
a run that reached Mainnet would spend real XRP on fabricated data. Two deliberate
mistakes are needed for that — a Mainnet RPC URL *and* a funded Mainnet seed — but the
cost of the mistake is real money, and the challenge asks specifically about spending
controls and safeguards.

So the check is an allowlist, not a blocklist: anything not recognised as a test network
is refused. A guard that cannot be disabled gets deleted by whoever needs Mainnet one
day, so there is an explicit, loud opt-in instead.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# Public XRPL test network JSON-RPC hosts.
TESTNET_RPC_HOSTS = frozenset(
    {
        "s.altnet.rippletest.net",
        "s.devnet.rippletest.net",
        "testnet.xrpl-labs.com",
        "clio.altnet.rippletest.net",
        "clio.devnet.rippletest.net",
        # Local or containerised standalone ledgers used in development.
        "localhost",
        "127.0.0.1",
    }
)

# x402 network identifiers: xrpl:1 is Testnet, xrpl:2 is Devnet. Mainnet (xrpl:0) is not
# listed on purpose.
TESTNET_NETWORK_IDS = frozenset({"xrpl:1", "xrpl:2"})

# Set to 1/true to settle on a network this module does not recognise. Doing so on
# Mainnet moves real XRP.
ALLOW_OVERRIDE_ENV = "LEDGER402_ALLOW_NON_TESTNET"


class NonTestnetBlocked(RuntimeError):
    """Refused: the configured network is not a recognised XRPL test network."""


def override_enabled() -> bool:
    return (os.getenv(ALLOW_OVERRIDE_ENV) or "").strip().lower() in {"1", "true", "yes"}


def is_testnet_rpc(rpc_url: str) -> bool:
    host = (urlparse(rpc_url).hostname or "").lower()
    return host in TESTNET_RPC_HOSTS


def is_testnet_network(network: str) -> bool:
    return (network or "").strip().lower() in TESTNET_NETWORK_IDS


def describe(rpc_url: str, network: str) -> str:
    return f"XRPL_RPC_URL={rpc_url!r}, XRPL_NETWORK={network!r}"


def assert_testnet(rpc_url: str, network: str) -> None:
    """Raise unless both the RPC endpoint and the network id are test networks.

    Called at the point of signing, not merely at startup: a process that changes its
    environment mid-run must not slip past the check.
    """
    if override_enabled():
        return

    problems = []
    if not is_testnet_rpc(rpc_url):
        problems.append(f"RPC host {urlparse(rpc_url).hostname!r} is not a known XRPL test network")
    if not is_testnet_network(network):
        problems.append(
            f"network id {network!r} is not a test network "
            f"(expected one of {', '.join(sorted(TESTNET_NETWORK_IDS))})"
        )
    if not problems:
        return

    raise NonTestnetBlocked(
        "Refusing to sign: Ledger402 settles on XRPL test networks only.\n"
        + "\n".join(f"  - {problem}" for problem in problems)
        + f"\n{describe(rpc_url, network)}\n"
        "All provider data in this build is synthetic, so a Mainnet settlement would "
        "spend real XRP on fabricated data.\n"
        f"If you genuinely intend that, set {ALLOW_OVERRIDE_ENV}=1."
    )


def current_status() -> dict[str, object]:
    """Network posture, for /capabilities and the UI."""
    rpc = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
    network = os.getenv("XRPL_NETWORK", "xrpl:1")
    return {
        "rpc_url": rpc,
        "network": network,
        "is_testnet": is_testnet_rpc(rpc) and is_testnet_network(network),
        "override_enabled": override_enabled(),
    }
