from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from apps.paid_provider import create_paid_provider

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# The cheaper, lower-quality paid option. Its purpose is to make ranking a real decision:
# the agent buys it only when the confidence target justifies a second settlement.
app = create_paid_provider(
    service="telemetry_provider",
    title="Ledger402 terminal telemetry provider",
    path="/intelligence/terminal-operations",
    provider_id="terminal-ops-telemetry",
    data_file="terminal_telemetry_data.json",
    price_env="TELEMETRY_PRICE_DROPS",
    default_price_drops="600",
    description="Terminal operations telemetry (synthetic)",
)
