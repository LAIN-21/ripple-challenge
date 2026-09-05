"""B2C dataset ingestion: curator wallets, x402 routes, live registry appends."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from xrpl.wallet import Wallet

from ledger402 import REPO_ROOT
from providers_data import PROVIDERS_REGISTRY

DATA_DIR = REPO_ROOT / "data" / "b2c"

COLUMN_TO_SIGNAL = {
    "customs_clearance_dwell_hrs": "customs_dwell",
    "chassis_availability_pct": "chassis_availability",
    "inspection_backlog_teu": "inspection_backlog",
}

B2C_SIGNALS = ["customs_dwell", "chassis_availability", "inspection_backlog"]
DEFAULT_B2C_PRICE_DROPS = 400
DEFAULT_QUALITY = 0.75
DEFAULT_FRESHNESS_HOURS = 1.0
MAX_UPLOAD_BYTES = 2_000_000

_lock = threading.Lock()
_dynamic: dict[str, dict[str, Any]] = {}
_royalties: dict[str, dict[str, Any]] = {}
_payment_gates: dict[str, Any] = {}


def reset() -> None:
    """Drop runtime B2C state. Tests only."""
    with _lock:
        for dataset_id in list(_dynamic):
            PROVIDERS_REGISTRY.pop(dataset_id, None)
        _dynamic.clear()
        _royalties.clear()
        _payment_gates.clear()


def dynamic_registry() -> dict[str, dict[str, Any]]:
    with _lock:
        return dict(_dynamic)


def get_dataset(dataset_id: str) -> dict[str, Any] | None:
    with _lock:
        return _dynamic.get(dataset_id)


def royalties() -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _royalties.values()]


def credit_royalty(dataset_id: str, *, drops: int, tx_hash: str | None) -> None:
    with _lock:
        current = _royalties.setdefault(
            dataset_id,
            {"dataset_id": dataset_id, "accrued_drops": 0, "settlements": 0, "last_tx_hash": None},
        )
        current["accrued_drops"] = int(current["accrued_drops"]) + int(drops)
        current["settlements"] = int(current["settlements"]) + 1
        if tx_hash:
            current["last_tx_hash"] = tx_hash


def _read_table(file: BinaryIO | str | Path | bytes, filename: str | None = None) -> list[dict[str, Any]]:
    if isinstance(file, (str, Path)):
        raw = Path(file).read_bytes()
        filename = filename or str(file)
    elif isinstance(file, bytes):
        raw = file
    else:
        raw = file.read()
        filename = filename or getattr(file, "name", "upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload exceeds 2 MB.")
    text = raw.decode("utf-8-sig")
    name = (filename or "").lower()
    if name.endswith(".json") or text.lstrip().startswith(("[", "{")):
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = parsed.get("rows") or parsed.get("data") or [parsed]
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("JSON upload must be a non-empty list of objects.")
        return [dict(row) for row in parsed if isinstance(row, Mapping)]
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError("CSV upload is empty.")
    return rows


def _to_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_signals(rows: list[dict[str, Any]]) -> dict[str, float]:
    signals: dict[str, float] = {}
    for row in reversed(rows):
        for column, signal in COLUMN_TO_SIGNAL.items():
            if signal in signals:
                continue
            number = _to_number(row.get(column) if column in row else row.get(signal))
            if number is not None:
                signals[signal] = number
        if len(signals) == len(B2C_SIGNALS):
            break
    if not signals:
        raise ValueError(
            "Upload must include at least one of: "
            + ", ".join(COLUMN_TO_SIGNAL)
        )
    return signals


log = logging.getLogger(__name__)


def provision_curator_wallet(*, timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Mint a display curator address; payouts escrow to XRPL_PAY_TO.

    Generated seeds are discarded. Direct settlement is never advertised for an
    address this process cannot spend from.
    """
    pay_to_env = (os.getenv("XRPL_PAY_TO") or "").strip()
    if not pay_to_env:
        raise ValueError(
            "XRPL_PAY_TO is required for B2C escrow settlement.\n"
            "Run `make wallet-setup` and copy the merchant address into `.env`."
        )
    skip_faucet = bool(os.getenv("LEDGER402_SKIP_FAUCET") or os.getenv("PYTEST_CURRENT_TEST"))
    curator_address = None
    if not skip_faucet:
        pool = None
        timed_out = False
        try:
            from xrpl.clients import JsonRpcClient
            from xrpl.wallet import generate_faucet_wallet

            def _faucet():
                rpc = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
                client = JsonRpcClient(rpc)
                return generate_faucet_wallet(client, debug=False)

            pool = ThreadPoolExecutor(max_workers=1)
            wallet = pool.submit(_faucet).result(timeout=timeout_seconds)
            curator_address = wallet.classic_address
        except TimeoutError:
            timed_out = True
            log.info(
                "Testnet faucet exceeded %.1fs; using a display address + escrow",
                timeout_seconds,
            )
        except Exception as exc:
            log.info("Testnet faucet unavailable; using a display address + escrow: %s", exc)
        finally:
            if pool is not None:
                pool.shutdown(wait=not timed_out, cancel_futures=True)
    if curator_address is None:
        curator_address = Wallet.create().classic_address
    return {
        "curator_address": curator_address,
        "pay_to": pay_to_env,
        "settlement_mode": "escrow",
        "seed": None,
    }


def register_b2c_dataset(
    file: BinaryIO | str | Path | bytes,
    curator_label: str,
    price_drops: int = DEFAULT_B2C_PRICE_DROPS,
    *,
    filename: str | None = None,
    provision: bool = True,
) -> dict[str, Any]:
    """Ingest CSV/JSON, mint a curator address, append into PROVIDERS_REGISTRY."""
    price = int(price_drops)
    if price <= 0:
        raise ValueError("price_drops must be a positive integer.")
    if price > 2000:
        raise ValueError("price_drops exceeds the per-purchase cap of 2000.")
    label = (curator_label or "").strip() or "Independent curator"
    rows = _read_table(file, filename=filename)
    signals_latest = _latest_signals(rows)
    dataset_id = f"b2c_{uuid.uuid4().hex[:12]}"
    wallet = provision_curator_wallet() if provision else {
        "curator_address": "rB2CTestCuratorAddress111111111111",
        "pay_to": (os.getenv("XRPL_PAY_TO") or "rB2CTestCuratorAddress111111111111"),
        "settlement_mode": "escrow",
        "seed": None,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / f"{dataset_id}.json"
    dest.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    payload = {
        "port_code": str(rows[-1].get("port_code") or "SGSIN"),
        "facility_name": str(rows[-1].get("terminal") or "Port of Singapore"),
        "rows": rows,
        "metrics": {
            "customs_clearance_dwell_hrs": signals_latest.get("customs_dwell"),
            "chassis_availability_pct": signals_latest.get("chassis_availability"),
            "inspection_backlog_teu": signals_latest.get("inspection_backlog"),
        },
        "customs_dwell": signals_latest.get("customs_dwell"),
        "chassis_availability": signals_latest.get("chassis_availability"),
        "inspection_backlog": signals_latest.get("inspection_backlog"),
        "freshness_hours": DEFAULT_FRESHNESS_HOURS,
        "quality_score": DEFAULT_QUALITY,
        "synthetic": True,
        "provider_id": dataset_id,
        "provider_name": label,
    }

    entry = {
        "id": dataset_id,
        "name": label,
        "curator_label": label,
        "category": "port_congestion",
        "base_url_env": "B2C_PROVIDER_URL",
        "path": f"/api/b2c/{dataset_id}",
        "endpoint": f"/api/b2c/{dataset_id}",
        "payment_required": True,
        "price_drops": price,
        "freshness_hours": DEFAULT_FRESHNESS_HOURS,
        "quality_score": DEFAULT_QUALITY,
        "expected_information_gain": 0.08,
        "signals": [s for s in B2C_SIGNALS if s in signals_latest],
        "description": f"Curated dataset from {label}",
        "license": "ODRL; Commercial_Derivative_Permitted",
        "curator_address": wallet["curator_address"],
        "pay_to": wallet["pay_to"],
        "settlement_mode": wallet["settlement_mode"],
        "payload": payload,
    }

    with _lock:
        _dynamic[dataset_id] = entry
        PROVIDERS_REGISTRY[dataset_id] = entry
        _royalties[dataset_id] = {
            "dataset_id": dataset_id,
            "accrued_drops": 0,
            "settlements": 0,
            "last_tx_hash": None,
            "curator_address": wallet["curator_address"],
        }

    return {
        "dataset_id": dataset_id,
        "curator_address": wallet["curator_address"],
        "pay_to": wallet["pay_to"],
        "settlement_mode": wallet["settlement_mode"],
        "endpoint": entry["endpoint"],
        "price_drops": price,
        "signals": entry["signals"],
        "provider": entry,
    }
