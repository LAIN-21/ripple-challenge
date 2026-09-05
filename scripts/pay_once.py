from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from ledger402 import payment, providers

load_dotenv(ROOT / ".env")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    os.chdir(ROOT)
    os.environ.setdefault("PYTHONPATH", str(ROOT))
    try:
        payment.require_wallet_env()
    except RuntimeError as exc:
        fail(str(exc))

    # Defaults to the satellite feed; pass a provider id to settle against another one,
    # e.g. `make pay-once ARGS=terminal-ops-telemetry`.
    provider_id = sys.argv[1] if len(sys.argv) > 1 else "satellite-logistics-intel"
    premium = providers.get_provider(provider_id)
    if premium is None:
        fail(f"{provider_id} missing from providers.json")
    if not premium.get("payment_required"):
        fail(f"{provider_id} is a free provider; there is nothing to settle.")
    url = providers.resolve_url(premium)
    price = int(premium.get("price_drops") or 0)

    unpaid = payment.observe_unpaid_402(url)
    print("Premium provider:")
    print(premium.get("name"))
    print()
    print("Initial response:")
    print(f"{unpaid.status_code} Payment Required" if unpaid.status_code == 402 else str(unpaid.status_code))
    print()
    print("Amount:")
    print(f"{price} drops / {price / 1_000_000:.4f} XRP")
    print()

    if unpaid.status_code != 402:
        fail(f"Expected HTTP 402 from unpaid GET, got {unpaid.status_code}: {unpaid.text[:400]}")

    result = payment.purchase_premium(
        url=url,
        run_id=f"pay-once-{provider_id}",
        provider_id=str(premium["id"]),
        expected_drops=price,
        remaining_budget_drops=price,
    )
    print("Payment:")
    print(result.state)
    print()
    if result.state != payment.SUCCESS:
        fail(result.error or "Payment did not succeed")

    tx = result.tx_hash or ""
    print("Transaction:")
    print(tx or "(missing hash)")
    print()
    print("Explorer:")
    print(payment.EXPLORER_TX.format(hash=tx) if tx else "—")
    print()
    if result.network_fee_drops is not None:
        print("XRPL network fee (separate from procurement budget):")
        print(f"{result.network_fee_drops} drops")
        print()
    print("Premium intelligence:")
    print(json.dumps(result.body, indent=2))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
