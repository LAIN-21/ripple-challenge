"""Shared factory for x402-gated data providers.

Both paid providers differ only in price, path, and payload, so the x402 wiring lives in
one place. Getting that wiring wrong is the one failure the demo cannot survive, and one
copy of it is one thing to keep correct.

Every paid response carries an ODRL agreement in the body and a compact form in the
`X-ODRL-Policy` header: the buyer receives usage rights in the same exchange that settles
the payment.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Response
from x402_xrpl.server import require_payment

from ledger402 import odrl
from ledger402.providers import load_json

DEFAULT_FACILITATOR_URL = "https://xrpl-facilitator-testnet.t54.ai"
DEFAULT_NETWORK = "xrpl:1"

# Ripple partner source tag, carried on settlements for attribution.
SOURCE_TAG = 804681468


def _missing_pay_to_message() -> str:
    return (
        "XRPL_PAY_TO is missing.\n"
        "Run `make wallet-setup`, copy the merchant address into `.env`,\n"
        "then run `make dev-start` again."
    )


def create_paid_provider(
    *,
    service: str,
    title: str,
    path: str,
    provider_id: str,
    data_file: str,
    price_env: str,
    default_price_drops: str,
    description: str,
) -> FastAPI:
    """Build a FastAPI app whose single data path is gated behind a real HTTP 402."""
    application = FastAPI(title=title)

    # Fail closed at startup: a provider with no payee would serve paid data for free.
    pay_to = (os.getenv("XRPL_PAY_TO") or "").strip()
    if not pay_to:
        raise RuntimeError(_missing_pay_to_message())

    price = (os.getenv(price_env) or default_price_drops).strip()

    application.middleware("http")(
        require_payment(
            path=path,
            price=price,
            pay_to_address=pay_to,
            facilitator_url=os.getenv("XRPL_FACILITATOR_URL", DEFAULT_FACILITATOR_URL),
            network=os.getenv("XRPL_NETWORK", DEFAULT_NETWORK),
            asset="XRP",
            description=description,
            source_tag=SOURCE_TAG,
        )
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @application.get(path)
    def intelligence(response: Response) -> dict[str, Any]:
        data = load_json(data_file)
        data["synthetic"] = True

        policy = odrl.agreement(
            provider_id=provider_id,
            dataset_id=provider_id,
            price_drops=int(price),
        )
        data["odrl"] = policy
        response.headers[odrl.ODRL_HEADER] = odrl.compact(policy)
        return data

    return application
