"""x402 challenge headers attached alongside the official SDK 402 body."""

from __future__ import annotations

from typing import Any, Mapping

DEFAULT_FACILITATOR = "https://xrpl-facilitator-testnet.t54.ai"
MACHINE_LICENSE = "ODRL; Commercial_Derivative_Permitted"


def payment_headers(
    *,
    amount_drops: int | str,
    destination: str,
    network: str = "xrpl:1",
    facilitator: str = DEFAULT_FACILITATOR,
) -> dict[str, str]:
    return {
        "WWW-Authenticate": "x402",
        "x-payment-protocol": "x402-xrpl",
        "x-payment-network": network,
        "x-payment-amount-drops": str(amount_drops),
        "x-payment-destination": destination,
        "x-payment-facilitator": facilitator,
        "x-machine-license": MACHINE_LICENSE,
    }


def apply_payment_headers(response: Any, headers: Mapping[str, str]) -> None:
    for key, value in headers.items():
        response.headers[key] = value
