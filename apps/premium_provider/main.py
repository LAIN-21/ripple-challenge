from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from x402_xrpl.server import require_payment

from ledger402.providers import load_json

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def create_app() -> FastAPI:
    application = FastAPI(title="Ledger402 premium provider")
    pay_to = os.getenv("XRPL_PAY_TO", "")
    if pay_to:
        application.middleware("http")(
            require_payment(
                path="/intelligence/port-congestion",
                price=os.getenv("XRPL_PRICE_DROPS", "1200"),
                pay_to_address=pay_to,
                facilitator_url=os.getenv(
                    "XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai"
                ),
                network=os.getenv("XRPL_NETWORK", "xrpl:1"),
                asset="XRP",
                description="Satellite logistics intelligence (synthetic)",
                source_tag=804681468,
            )
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "premium_provider"}

    @application.get("/intelligence/port-congestion")
    def port_congestion() -> dict:
        data = load_json("premium_satellite_data.json")
        data["synthetic"] = True
        return data

    return application


app = create_app()
