from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet

RPC = "https://s.altnet.rippletest.net:51234/"


def fund_wallet() -> Wallet:
    client = JsonRpcClient(RPC)
    return generate_faucet_wallet(client, debug=False)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    print("Funding Testnet wallets via xrpl-py faucet helper...")
    buyer = fund_wallet()
    merchant = fund_wallet()
    print(
        f"""
==================================================
Ledger402 XRPL Testnet Setup
==================================================

BUYER ADDRESS:
{buyer.classic_address}

BUYER SEED — PRIVATE:
{buyer.seed}

MERCHANT ADDRESS:
{merchant.classic_address}

Copy these values into `.env`:

XRPL_WALLET_SEED={buyer.seed}
XRPL_PAY_TO={merchant.classic_address}

The following can remain unchanged from `.env.example`:

XRPL_RPC_URL=https://s.altnet.rippletest.net:51234/
XRPL_NETWORK=xrpl:1
XRPL_FACILITATOR_URL=https://xrpl-facilitator-testnet.t54.ai

IMPORTANT:
- Never commit the buyer seed.
- `.env` must be gitignored.
- Buyer and merchant addresses are public.
- Merchant seed is not required by the application for the current MVP.
==================================================
"""
    )


if __name__ == "__main__":
    main()
