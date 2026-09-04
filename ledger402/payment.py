from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import requests
from xrpl.wallet import Wallet

from ledger402 import audit

try:
    from x402_xrpl.clients import decode_payment_response, x402_requests
except ImportError:  # pragma: no cover - import path differs by SDK layout
    from x402_xrpl.clients.base import decode_payment_response
    from x402_xrpl.clients.requests import x402_requests


NOT_STARTED = "NOT_STARTED"
PENDING = "PENDING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

EXPLORER_TX = "https://testnet.xrpl.org/transactions/{hash}"


@dataclass
class PurchaseRecord:
    state: str = NOT_STARTED
    http_402_status: int | None = None
    tx_hash: str | None = None
    network_fee_drops: int | None = None
    body: Any = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


_cache: dict[str, PurchaseRecord] = {}
_lock = Lock()


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def _key(run_id: str, provider_id: str) -> str:
    return f"{run_id}:{provider_id}"


def _missing_wallet_message() -> str:
    return (
        "XRPL wallet configuration missing.\n"
        "Run `make wallet-setup`, copy the printed values into `.env`,\n"
        "then run `make dev-start` again."
    )


def require_wallet_env() -> None:
    if not os.getenv("XRPL_WALLET_SEED") or not os.getenv("XRPL_PAY_TO"):
        raise RuntimeError(_missing_wallet_message())


def _header(response: requests.Response, name: str) -> str | None:
    for key, value in response.headers.items():
        if key.lower() == name.lower():
            return value
    return None


def extract_tx_hash(decoded: dict[str, Any] | None) -> str | None:
    if not decoded:
        return None
    for key in ("transaction", "txHash", "tx_hash", "hash"):
        value = decoded.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = value.get("hash") or value.get("transaction")
            if isinstance(nested, str) and nested:
                return nested
    return None


def extract_network_fee_drops(decoded: dict[str, Any] | None) -> int | None:
    if not decoded:
        return None
    for key in ("networkFee", "network_fee", "fee", "feeDrops", "fee_drops"):
        value = decoded.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def observe_unpaid_402(url: str, timeout: float = 30.0) -> requests.Response:
    response = requests.get(url, timeout=timeout)
    return response


def _buyer_session() -> requests.Session:
    seed = os.environ["XRPL_WALLET_SEED"]
    rpc = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
    network = os.getenv("XRPL_NETWORK", "xrpl:1")
    buyer = Wallet.from_seed(seed)
    return x402_requests(
        buyer,
        rpc_url=rpc,
        network_filter=network,
        scheme_filter="exact",
    )


def purchase_premium(
    *,
    url: str,
    run_id: str,
    provider_id: str,
    log: list[dict[str, Any]] | None = None,
    timeout: float = 180.0,
) -> PurchaseRecord:
    """Pay for a premium URL after observing a real 402. Process-local idempotency."""
    cache_key = _key(run_id, provider_id)
    with _lock:
        existing = _cache.get(cache_key)
        if existing and existing.state in {PENDING, SUCCESS, UNKNOWN}:
            return existing
        record = PurchaseRecord(state=PENDING)
        _cache[cache_key] = record

    events = log if log is not None else record.events
    try:
        unpaid = observe_unpaid_402(url, timeout=min(timeout, 30.0))
        record.http_402_status = unpaid.status_code
        audit.add(
            events,
            "HTTP_402_OBSERVED",
            status_code=unpaid.status_code,
            note="Unpaid GET. Invoice from this response is not assumed to be the settled invoice.",
        )
        if unpaid.status_code != 402:
            record.state = FAILED
            record.error = f"Expected HTTP 402, got {unpaid.status_code}"
            return record

        audit.add(events, "X402_PAYMENT_NEGOTIATION_STARTED", url=url)
        session = _buyer_session()
        paid = session.get(url, timeout=timeout)
        header = _header(paid, "PAYMENT-RESPONSE")
        decoded = None
        if header:
            try:
                decoded = decode_payment_response(header)
            except Exception:
                try:
                    decoded = json.loads(header)
                except Exception:
                    decoded = None
        tx_hash = extract_tx_hash(decoded if isinstance(decoded, dict) else None)
        fee = extract_network_fee_drops(decoded if isinstance(decoded, dict) else None)

        if paid.status_code == 200:
            record.state = SUCCESS
            record.tx_hash = tx_hash
            record.network_fee_drops = fee
            record.body = paid.json() if paid.content else {}
            audit.add(
                events,
                "XRPL_PAYMENT_CONFIRMED",
                tx_hash=tx_hash,
                network_fee_drops=fee,
                explorer=EXPLORER_TX.format(hash=tx_hash) if tx_hash else None,
            )
            audit.add(events, "PREMIUM_RESOURCE_UNLOCKED", status_code=200)
            return record

        record.state = FAILED
        record.error = f"Paid request returned HTTP {paid.status_code}: {paid.text[:300]}"
        return record
    except Exception as exc:  # payment may already have been submitted
        record.state = UNKNOWN
        record.error = str(exc)
        return record
