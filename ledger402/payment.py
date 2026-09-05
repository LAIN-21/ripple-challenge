from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable, Mapping

import requests
from xrpl.clients import JsonRpcClient
from xrpl.ledger import get_latest_validated_ledger_sequence
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.transactions import EscrowCreate, EscrowFinish, Memo, Payment
from xrpl.transaction import autofill, sign
from xrpl.utils import datetime_to_ripple_time
from xrpl.wallet import Wallet

from ledger402 import audit
from ledger402 import network as xrpl_network

try:
    from x402_xrpl.clients import decode_payment_response, x402_requests
except ImportError:  # pragma: no cover - import path differs by SDK layout
    from x402_xrpl.clients.base import decode_payment_response
    from x402_xrpl.clients.requests import x402_requests

from x402_xrpl.client.presigned_payment_payer import (
    build_payment_header_for_signed_blob,
    invoice_id_to_invoice_id_field,
    invoice_id_to_memo_hex,
    text_to_memo_hex,
)
from x402_xrpl.types import PaymentRequirements


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
SUPPORTED_FUNDING_ASSETS = frozenset({"XRP", "RLUSD"})

# "ledger402:audit" as an XRPL MemoType hex string. Stamped on every atomic-memo
# payment so the settlement and the proof of what was requested land in the same
# signed transaction: an auditor recomputing compute_evidence_hash() from the
# published invoice can verify MemoData on-ledger without trusting this codebase.
AUDIT_MEMO_TYPE_HEX = "6C65646765723430323A6175646974"

# XRPL Testnet RLUSD (Ripple USD) issuer and 160-bit currency code, used for the
# cross-currency (RLUSD -> XRP) settlement path.
RLUSD_ISSUER_TESTNET = "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV"
RLUSD_CURRENCY_HEX = "524C555344000000000000000000000000000000"


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
    # SHA-256 hex of the requested payload spec, embedded as MemoData on the settling
    # Payment. Set whenever an evidence_hash is supplied, independent of outcome: it
    # records what proof was bound into the outgoing transaction.
    memo_proof: str | None = None


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


def normalize_funding_asset(raw: str | None = None) -> str:
    """Blank env defaults to XRP. Any other nonempty value must be XRP or RLUSD."""
    value = (raw if raw is not None else os.getenv("LEDGER402_FUNDING_ASSET") or "").strip().upper()
    if not value:
        return "XRP"
    if value not in SUPPORTED_FUNDING_ASSETS:
        raise ValueError(
            f"Unsupported LEDGER402_FUNDING_ASSET={raw if raw is not None else os.getenv('LEDGER402_FUNDING_ASSET')!r}. "
            "Use XRP or RLUSD."
        )
    return value


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


def compute_evidence_hash(payload_spec: Any) -> str:
    """SHA-256 hex digest of the requested payload/evidence specification.

    Embedded on-ledger as the audit Memo (see AUDIT_MEMO_TYPE_HEX) so a settled
    payment and the proof of what was requested become mathematically atomic: an
    auditor can recompute this hash from the published invoice line item and
    compare it to MemoData on the XRPL Testnet.
    """
    canonical = json.dumps(payload_spec, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


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
    evidence_hash: str | None = None,
    funding_asset: str = "XRP",
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

    header_factory = None
    if evidence_hash:
        # Atomic memo (and, opt-in, cross-currency funding) require signing our own
        # transaction rather than the SDK's default invoice-only payer.
        header_factory = _atomic_memo_payment_header_factory(
            wallet=buyer,
            rpc_url=rpc,
            evidence_hash=evidence_hash,
            funding_asset=funding_asset,
        )

    return x402_requests(
        buyer,
        rpc_url=rpc,
        network_filter=network,
        scheme_filter=EXPECTED_SCHEME,
        payment_requirements_selector=selector,
        payment_header_factory=header_factory,
    )


def _atomic_memo_payment_header_factory(
    *,
    wallet: Wallet,
    rpc_url: str,
    evidence_hash: str,
    invoice_binding: str = "both",
    funding_asset: str = "XRP",
    rlusd_issuer: str = RLUSD_ISSUER_TESTNET,
    rlusd_headroom: float = 1.15,
) -> Callable[..., str]:
    """Build a PaymentHeaderFactory that signs its own Payment transaction.

    Bypasses the SDK's default XRPLPresignedPaymentPayer (which only ever emits an
    invoice memo) so two native primitives can be embedded in the same signed
    transaction as the settlement itself:

    - an audit Memo (AUDIT_MEMO_TYPE_HEX / evidence_hash), atomic proof of what was
      requested; and
    - optionally, a cross-currency SendMax (RLUSD) funding an XRP-denominated
      requirement, so the XRPL native DEX autobridges the two assets inline.
    """
    client = JsonRpcClient(rpc_url)

    def factory(reqs: PaymentRequirements, *, extensions: Mapping[str, Any] | None = None) -> str:
        del extensions  # this demo payer issues no verifiable-intent extensions
        inv = reqs.invoice_id()
        if not inv:
            raise ValueError('invoice_id is required (expected PaymentRequirements.extra["invoiceId"])')

        memos: list[Memo] = []
        if invoice_binding in ("memos", "both"):
            memos.append(Memo(memo_data=invoice_id_to_memo_hex(inv)))
        memos.append(
            Memo(
                memo_type=AUDIT_MEMO_TYPE_HEX,
                memo_data=evidence_hash.upper(),
                memo_format=text_to_memo_hex("text/plain"),
            )
        )
        invoice_id_field = (
            invoice_id_to_invoice_id_field(inv) if invoice_binding in ("invoice_id", "both") else None
        )

        asset = str(reqs.asset or "XRP")
        if asset.upper() != "XRP":
            raise ValueError("Atomic-memo payer only settles XRP-denominated requirements")
        drops = str(int(reqs.amount))

        send_max: str | IssuedCurrencyAmount | None = None
        normalized_funding_asset = normalize_funding_asset(funding_asset)
        if normalized_funding_asset == "RLUSD":
            # Cross-currency settlement: the buyer's desk holds RLUSD; the merchant is
            # paid in drops. SendMax caps spend in the funding asset while Amount stays
            # pinned to the quoted XRP requirement — the native DEX autobridges the
            # difference inside this one signed transaction (requires the merchant's
            # requirement to advertise extra.crossCurrency = true).
            xrp_value = int(drops) / 1_000_000
            ceiling = max(round(xrp_value * rlusd_headroom, 6), 0.000001)
            send_max = IssuedCurrencyAmount(
                currency=RLUSD_CURRENCY_HEX,
                issuer=rlusd_issuer,
                value=f"{ceiling:.6f}",
            )

        extra = reqs.extra if isinstance(reqs.extra, Mapping) else {}
        source_tag: int | None = None
        destination_tag: int | None = None
        raw_source = extra.get("sourceTag")
        if raw_source is not None:
            source_tag = int(raw_source)
        raw_dest = extra.get("destinationTag")
        if raw_dest is not None:
            destination_tag = int(raw_dest)

        current_validated_ledger = get_latest_validated_ledger_sequence(client)
        max_ledger_delta = int(math.ceil(int(reqs.max_timeout_seconds) / 5.0) + 2)
        last_ledger_sequence = int(current_validated_ledger) + max_ledger_delta

        payment_tx = Payment(
            account=wallet.classic_address,
            destination=reqs.pay_to,
            amount=drops,
            send_max=send_max,
            memos=memos,
            invoice_id=invoice_id_field,
            source_tag=source_tag,
            destination_tag=destination_tag,
            last_ledger_sequence=last_ledger_sequence,
        )
        filled = autofill(payment_tx, client)
        signed = sign(filled, wallet)
        return build_payment_header_for_signed_blob(
            req=reqs,
            signed_tx_blob=signed.blob(),
            invoice_id=inv,
        )

    return factory


def _der_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    encoded = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(encoded)]) + encoded


def _der_integer(n: int) -> bytes:
    if n <= 0:
        return b"\x00"
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    if body[0] & 0x80:
        body = b"\x00" + body
    return body


def build_preimage_condition(preimage: bytes) -> tuple[str, str]:
    """PREIMAGE-SHA-256 crypto-condition and fulfillment, hex-encoded for
    EscrowCreate.Condition / EscrowFinish.Fulfillment.

    Follows the crypto-conditions DER layout XRPL documents
    (draft-thomas-crypto-conditions-02 section 8.1). Verified against xrpl.org's own
    reference vector: an empty preimage yields
    condition=A0258020E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855810100
    and fulfillment=A0028000.
    """
    fingerprint = hashlib.sha256(preimage).digest()
    cost = _der_integer(len(preimage))
    fingerprint_field = b"\x80" + _der_length(len(fingerprint)) + fingerprint
    cost_field = b"\x81" + _der_length(len(cost)) + cost
    condition_body = fingerprint_field + cost_field
    condition = b"\xA0" + _der_length(len(condition_body)) + condition_body

    preimage_field = b"\x80" + _der_length(len(preimage)) + preimage
    fulfillment = b"\xA0" + _der_length(len(preimage_field)) + preimage_field

    return condition.hex().upper(), fulfillment.hex().upper()


def build_conditional_escrow(
    *,
    wallet: Wallet,
    destination: str,
    amount_drops: int,
    expected_data_hash: str | None = None,
    preimage: bytes | None = None,
    finish_after_seconds: int | None = None,
    cancel_after_seconds: int | None = None,
    rpc_url: str | None = None,
) -> dict[str, Any]:
    """Build an EscrowCreate secured by a PREIMAGE-SHA-256 crypto-condition.

    The on-ledger condition is the preimage hash only. `expected_data_hash` is
    off-ledger metadata for operators; it does not enter `condition` or
    `fulfillment`. Anyone who holds the fulfillment can finish the escrow.

    Returns the condition/fulfillment pair plus the unsigned transaction. Hold
    the fulfillment until delivery is verified off-ledger, then pass it to
    `build_escrow_finish`. If `rpc_url` is given the transaction is also
    autofilled and signed.
    """
    secret = preimage or secrets.token_bytes(32)
    condition, fulfillment = build_preimage_condition(secret)

    now = datetime.now(timezone.utc)
    finish_after = (
        datetime_to_ripple_time(now + timedelta(seconds=finish_after_seconds))
        if finish_after_seconds
        else None
    )
    cancel_after = (
        datetime_to_ripple_time(now + timedelta(seconds=cancel_after_seconds))
        if cancel_after_seconds
        else None
    )

    escrow_create = EscrowCreate(
        account=wallet.classic_address,
        destination=destination,
        amount=str(int(amount_drops)),
        condition=condition,
        finish_after=finish_after,
        cancel_after=cancel_after,
    )

    result: dict[str, Any] = {
        "condition": condition,
        "fulfillment": fulfillment,
        "evidence_hash": expected_data_hash,
        "transaction": escrow_create.to_xrpl(),
    }

    if rpc_url:
        client = JsonRpcClient(rpc_url)
        filled = autofill(escrow_create, client)
        signed = sign(filled, wallet)
        result["signed_tx_blob"] = signed.blob()

    return result


def build_escrow_finish(
    *,
    wallet: Wallet,
    owner: str,
    offer_sequence: int,
    condition: str,
    fulfillment: str,
) -> EscrowFinish:
    """The provider's half of conditional delivery: reveal `fulfillment` to release
    funds an `EscrowCreate` locked behind `condition`."""
    return EscrowFinish(
        account=wallet.classic_address,
        owner=owner,
        offer_sequence=offer_sequence,
        condition=condition,
        fulfillment=fulfillment,
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
    evidence_hash: str | None = None,
    funding_asset: str | None = None,
) -> PurchaseRecord:
    """Pay for a premium URL after observing a real 402. Process-local idempotency.

    When `evidence_hash` is given, the settling Payment carries it as an on-ledger
    audit Memo (see AUDIT_MEMO_TYPE_HEX): the payment and the proof of what was
    requested become atomic. `funding_asset="RLUSD"` additionally funds the payment
    from RLUSD via a cross-currency SendMax, autobridged to XRP by the native DEX.
    """
    cache_key = _key(run_id, provider_id)
    with _lock:
        existing = _cache.get(cache_key)
        if existing and existing.state in {PENDING, SUCCESS, UNKNOWN}:
            return existing

    require_wallet_env()
    funding_asset = normalize_funding_asset(funding_asset)

    with _lock:
        existing = _cache.get(cache_key)
        if existing and existing.state in {PENDING, SUCCESS, UNKNOWN}:
            return existing
        record = PurchaseRecord(state=PENDING, memo_proof=evidence_hash)
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
            evidence_hash=evidence_hash,
            funding_asset=funding_asset,
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
