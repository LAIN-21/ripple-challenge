from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Mapping

import requests
from xrpl.wallet import Wallet

from ledger402 import audit
from ledger402 import network as xrpl_network

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
REQUIREMENT_REJECTED = "REQUIREMENT_REJECTED"
CONFIG_ERROR = "CONFIG_ERROR"

EXPLORER_TX = "https://testnet.xrpl.org/transactions/{hash}"
EXPECTED_ASSET = "XRP"
EXPECTED_SCHEME = "exact"


class PaymentRequirementRejected(Exception):
    """Pre-sign rejection: no matching 402 requirement, nothing submitted."""


@dataclass
class PurchaseRecord:
    state: str = NOT_STARTED
    http_402_status: int | None = None
    tx_hash: str | None = None
    network_fee_drops: int | None = None
    body: Any = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    settlement: dict[str, Any] | None = None


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


def _req_field(req: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in req and req[name] is not None:
            return req[name]
    return None


def _amount_drops(req: Mapping[str, Any]) -> int | None:
    raw = _req_field(req, "amount", "maxAmountRequired")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def requirement_matches(
    req: Mapping[str, Any],
    *,
    expected_drops: int,
    remaining_budget_drops: int,
    expected_pay_to: str,
    expected_asset: str = EXPECTED_ASSET,
    expected_network: str = "xrpl:1",
    expected_scheme: str = EXPECTED_SCHEME,
) -> bool:
    """Compare an untrusted 402 requirement against trusted expected terms."""
    amount = _amount_drops(req)
    if amount is None:
        return False
    if amount != int(expected_drops):
        return False
    if amount > int(remaining_budget_drops):
        return False
    asset = str(_req_field(req, "asset", "currency") or "")
    if asset != expected_asset:
        return False
    pay_to = str(_req_field(req, "payTo", "pay_to") or "")
    if pay_to != expected_pay_to:
        return False
    network = str(_req_field(req, "network") or "")
    if network != expected_network:
        return False
    scheme = str(_req_field(req, "scheme") or "")
    if scheme != expected_scheme:
        return False
    return True


def select_payment_requirement(
    accepts: Any,
    network_filter: str | None = None,
    scheme_filter: str | None = None,
    max_value: Any = None,
    *,
    expected_drops: int,
    remaining_budget_drops: int,
    expected_pay_to: str,
    expected_network: str,
) -> Mapping[str, Any]:
    del network_filter, scheme_filter, max_value
    for req in accepts or []:
        if isinstance(req, Mapping) and requirement_matches(
            req,
            expected_drops=expected_drops,
            remaining_budget_drops=remaining_budget_drops,
            expected_pay_to=expected_pay_to,
            expected_network=expected_network,
        ):
            return req
    raise PaymentRequirementRejected(
        "No 402 payment requirement matched expected provider terms "
        f"(amount={expected_drops} drops, asset={EXPECTED_ASSET}, "
        f"payTo={expected_pay_to}, network={expected_network}, scheme={EXPECTED_SCHEME})."
    )


def _buyer_session(
    *,
    expected_drops: int,
    remaining_budget_drops: int,
    selector_state: dict[str, Any],
    expected_pay_to: str | None = None,
) -> requests.Session:
    seed = os.environ["XRPL_WALLET_SEED"]
    rpc = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
    network = os.getenv("XRPL_NETWORK", "xrpl:1")
    pay_to = (expected_pay_to or os.environ.get("XRPL_PAY_TO") or "").strip()
    if not pay_to:
        raise RuntimeError(_missing_wallet_message())

    # Checked here rather than only at startup: this is the last point before a key
    # signs anything, so a mid-run environment change cannot slip past it.
    xrpl_network.assert_testnet(rpc, network)

    buyer = Wallet.from_seed(seed)

    def selector(
        accepts: Any,
        network_filter: str | None = None,
        scheme_filter: str | None = None,
        max_value: Any = None,
    ) -> Mapping[str, Any]:
        try:
            return select_payment_requirement(
                accepts,
                network_filter,
                scheme_filter,
                max_value,
                expected_drops=expected_drops,
                remaining_budget_drops=remaining_budget_drops,
                expected_pay_to=pay_to,
                expected_network=network,
            )
        except PaymentRequirementRejected as exc:
            selector_state["rejected"] = exc
            raise

    return x402_requests(
        buyer,
        rpc_url=rpc,
        network_filter=network,
        scheme_filter=EXPECTED_SCHEME,
        payment_requirements_selector=selector,
    )


def _decode_payment_header(response: requests.Response) -> dict[str, Any] | None:
    header = _header(response, "PAYMENT-RESPONSE")
    if not header:
        return None
    try:
        decoded = decode_payment_response(header)
    except Exception:
        try:
            decoded = json.loads(header)
        except Exception:
            return None
    return decoded if isinstance(decoded, dict) else None


def purchase_premium(
    *,
    url: str,
    run_id: str,
    provider_id: str,
    expected_drops: int,
    remaining_budget_drops: int,
    log: list[dict[str, Any]] | None = None,
    timeout: float = 180.0,
    expected_pay_to: str | None = None,
) -> PurchaseRecord:
    """Pay for a premium URL after observing a real 402. Process-local idempotency."""
    cache_key = _key(run_id, provider_id)
    with _lock:
        existing = _cache.get(cache_key)
        if existing and existing.state in {PENDING, SUCCESS, UNKNOWN}:
            return existing

    require_wallet_env()

    with _lock:
        existing = _cache.get(cache_key)
        if existing and existing.state in {PENDING, SUCCESS, UNKNOWN}:
            return existing
        record = PurchaseRecord(state=PENDING)
        _cache[cache_key] = record

    events = log if log is not None else record.events
    selector_state: dict[str, Any] = {"rejected": None}
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
        session = _buyer_session(
            expected_drops=expected_drops,
            remaining_budget_drops=remaining_budget_drops,
            selector_state=selector_state,
            expected_pay_to=expected_pay_to,
        )
        paid = session.get(url, timeout=timeout)
        if selector_state["rejected"] is not None:
            record.state = REQUIREMENT_REJECTED
            record.error = str(selector_state["rejected"])
            return record

        decoded = _decode_payment_header(paid)
        tx_hash = extract_tx_hash(decoded)
        fee = extract_network_fee_drops(decoded)
        record.tx_hash = tx_hash
        record.network_fee_drops = fee
        if decoded:
            record.settlement = decoded

        if paid.status_code == 200:
            record.state = SUCCESS
            record.body = paid.json() if paid.content else {}
            audit.add(
                events,
                "XRPL_PAYMENT_CONFIRMED",
                tx_hash=tx_hash,
                # Carried on the event so a consumer reading only the log can account for
                # the spend without correlating back to the approval.
                price_drops=int(expected_drops),
                network_fee_drops=fee,
                explorer=EXPLORER_TX.format(hash=tx_hash) if tx_hash else None,
            )
            audit.add(events, "PREMIUM_RESOURCE_UNLOCKED", status_code=200)
            return record

        record.state = UNKNOWN
        record.error = f"Paid request returned HTTP {paid.status_code}: {paid.text[:300]}"
        return record
    except PaymentRequirementRejected as exc:
        record.state = REQUIREMENT_REJECTED
        record.error = str(exc)
        return record
    except xrpl_network.NonTestnetBlocked as exc:
        # Refused before the wallet was constructed, so nothing was signed or submitted.
        # Reporting this as UNKNOWN would wrongly imply a transaction might be in flight.
        record.state = CONFIG_ERROR
        record.error = str(exc)
        audit.add(events, "NON_TESTNET_BLOCKED", reason=str(exc))
        return record
    except Exception as exc:  # payment may already have been submitted
        record.state = UNKNOWN
        record.error = str(exc)
        return record
