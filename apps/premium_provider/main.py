from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from apps.paid_provider import create_paid_provider

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = create_paid_provider(
    service="premium_provider",
    title="Ledger402 premium provider",
    path="/intelligence/port-congestion",
    provider_id="satellite-logistics-intel",
    data_file="premium_satellite_data.json",
    price_env="XRPL_PRICE_DROPS",
    default_price_drops="1200",
    description="Satellite logistics intelligence (synthetic)",
)
