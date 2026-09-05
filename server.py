"""Ledger402 supply-side gateway: B2B x402 feeds + B2C curator marketplace."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from x402_xrpl.server import require_payment
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import Tx

from ledger402 import REPO_ROOT
from ledger402 import headers as x402_headers
from ledger402 import marketplace, odrl, providers
from ledger402.marketplace import DEFAULT_B2C_PRICE_DROPS, MAX_UPLOAD_BYTES
from providers_data import PROVIDERS_REGISTRY

load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_FACILITATOR = x402_headers.DEFAULT_FACILITATOR
DEFAULT_NETWORK = "xrpl:1"
SOURCE_TAG = 804681468
CONSUMED_PATH = REPO_ROOT / "data" / "consumed_tx_hashes.json"
UPLOAD_CHUNK = 64 * 1024
# Multipart envelope is larger than the file; reject obviously oversized bodies early.
UPLOAD_CONTENT_LENGTH_SLACK = 65_536

app = FastAPI(title="Ledger402 provider gateway")

_gates: dict[str, Any] = {}
_consumed: set[str] = set()
_consumed_lock = threading.Lock()
_consumed_loaded = False


def _merchant() -> str:
    return (os.getenv("XRPL_PAY_TO") or "").strip()


def _facilitator() -> str:
    return os.getenv("XRPL_FACILITATOR_URL", DEFAULT_FACILITATOR)


def _network() -> str:
    return os.getenv("XRPL_NETWORK", DEFAULT_NETWORK)


def _persist_consumed() -> bool:
    return not os.getenv("PYTEST_CURRENT_TEST")


def reset_consumed_hashes() -> None:
    """Drop the one-use hash set. Tests only."""
    global _consumed_loaded
    with _consumed_lock:
        _consumed.clear()
        _consumed_loaded = True


def _load_consumed() -> None:
    global _consumed_loaded
    if _consumed_loaded:
        return
    _consumed_loaded = True
    if not _persist_consumed() or not CONSUMED_PATH.exists():
        return
    try:
        raw = json.loads(CONSUMED_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _consumed.update(str(item).upper() for item in raw if item)
    except Exception:
        return


def _save_consumed() -> None:
    if not _persist_consumed():
        return
    CONSUMED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONSUMED_PATH.write_text(json.dumps(sorted(_consumed)), encoding="utf-8")


def consume_hash(tx_hash: str) -> bool:
    """Record a hash as spent. False if it was already used."""
    cleaned = tx_hash.strip().upper()
    if not cleaned:
        return False
    with _consumed_lock:
        _load_consumed()
        if cleaned in _consumed:
            return False
        _consumed.add(cleaned)
        _save_consumed()
        return True


def _paid_spec(path: str) -> dict[str, Any] | None:
    if path == "/api/b2b/satellite-logistics":
        spec = dict(PROVIDERS_REGISTRY["satellite_logistics_paid"])
        spec["id"] = "satellite_logistics_paid"
        spec["pay_to"] = spec.get("pay_to") or _merchant()
        return spec
    if path == "/api/b2b/terminal-telemetry":
        spec = dict(PROVIDERS_REGISTRY["terminal_telemetry_paid"])
        spec["id"] = "terminal_telemetry_paid"
        spec["pay_to"] = spec.get("pay_to") or _merchant()
        return spec
    if path.startswith("/api/b2c/") and path != "/api/b2c/upload":
        dataset_id = path.rsplit("/", 1)[-1]
        dataset = marketplace.get_dataset(dataset_id) or PROVIDERS_REGISTRY.get(dataset_id)
        if dataset:
            return dict(dataset)
    return None


def _gate_for(path: str, spec: dict[str, Any]):
    pay_to = str(spec.get("pay_to") or _merchant())
    price = str(int(spec.get("price_drops") or 0))
    key = f"{path}:{price}:{pay_to}"
    if key not in _gates:
        if not pay_to:
            raise RuntimeError(
                "XRPL_PAY_TO is missing.\n"
                "Run `make wallet-setup`, copy the merchant address into `.env`,\n"
                "then run `make dev-start` again."
            )
        _gates[key] = require_payment(
            path=path,
            price=price,
            pay_to_address=pay_to,
            facilitator_url=_facilitator(),
            network=_network(),
            asset="XRP",
            description=str(spec.get("description") or path),
            source_tag=SOURCE_TAG,
        )
    return _gates[key]


def _header(request: Request, name: str) -> str | None:
    for key, value in request.headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _fetch_tx_result(tx_hash: str) -> dict[str, Any]:
    rpc = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
    client = JsonRpcClient(rpc)
    response = client.request(Tx(transaction=tx_hash))
    result = response.result if hasattr(response, "result") else {}
    return result if isinstance(result, dict) else {}


def _verify_tx_hash(tx_hash: str, spec: dict[str, Any]) -> bool:
    cleaned = tx_hash.strip()
    if len(cleaned) != 64:
        return False
    try:
        int(cleaned, 16)
    except ValueError:
        return False
    expected_dest = str(spec.get("pay_to") or _merchant())
    expected_drops = str(int(spec.get("price_drops") or 0))
    if not expected_dest or not expected_drops:
        return False
    try:
        result = _fetch_tx_result(cleaned)
    except Exception:
        return False
    if result.get("validated") is not True:
        return False
    tx = result.get("tx_json") or result.get("transaction") or result
    if not isinstance(tx, dict):
        return False
    if str(tx.get("TransactionType") or "") != "Payment":
        return False
    dest = str(tx.get("Destination") or "")
    if dest != expected_dest:
        return False
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    if str(meta.get("TransactionResult") or "") != "tesSUCCESS":
        return False
    delivered = meta.get("delivered_amount")
    if not isinstance(delivered, str) or delivered != expected_drops:
        return False
    return True


@app.middleware("http")
async def payment_gate(request: Request, call_next):
    path = request.url.path
    spec = _paid_spec(path)
    if spec is None:
        return await call_next(request)

    alt_hash = _header(request, "x402-Tx-Hash") or _header(request, "PAYMENT-SIGNATURE")
    if alt_hash and _verify_tx_hash(alt_hash, spec) and consume_hash(alt_hash):
        return await call_next(request)

    try:
        gate = _gate_for(path, spec)
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    response = await gate(request, call_next)
    if getattr(response, "status_code", 0) == 402:
        x402_headers.apply_payment_headers(
            response,
            x402_headers.payment_headers(
                amount_drops=int(spec.get("price_drops") or 0),
                destination=str(spec.get("pay_to") or _merchant()),
                network=_network(),
                facilitator=_facilitator(),
            ),
        )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "provider_gateway"}


@app.get("/catalog")
def catalog() -> dict[str, Any]:
    return {"providers": providers.load_registry()}


@app.get("/royalties")
def royalties() -> dict[str, Any]:
    return {"royalties": marketplace.royalties()}


def _paid_body(provider_id: str, response: Response) -> dict[str, Any]:
    spec = PROVIDERS_REGISTRY.get(provider_id) or marketplace.get_dataset(provider_id) or {}
    data = providers.flatten_payload(provider_id, spec if spec else None)
    price = int(spec.get("price_drops") or 0)
    policy = odrl.agreement(
        provider_id=provider_id,
        dataset_id=provider_id,
        price_drops=price,
        purpose="commercialDerivative",
    )
    data["odrl"] = policy
    response.headers[odrl.ODRL_HEADER] = odrl.compact(policy)
    return data


@app.get("/api/b2b/public-stats")
def public_stats() -> dict[str, Any]:
    return providers.flatten_payload("public_port_stats")


@app.get("/api/b2b/satellite-logistics")
def satellite(response: Response) -> dict[str, Any]:
    return _paid_body("satellite_logistics_paid", response)


@app.get("/api/b2b/terminal-telemetry")
def telemetry(response: Response) -> dict[str, Any]:
    return _paid_body("terminal_telemetry_paid", response)


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds 2 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/b2c/upload")
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    curator_label: str = Form("Independent curator"),
    price_drops: int = Form(DEFAULT_B2C_PRICE_DROPS),
) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES + UPLOAD_CONTENT_LENGTH_SLACK:
                raise HTTPException(status_code=413, detail="Upload exceeds 2 MB.")
        except ValueError:
            pass
    raw = await _read_upload(file, MAX_UPLOAD_BYTES)
    try:
        result = await run_in_threadpool(
            marketplace.register_b2c_dataset,
            raw,
            curator_label,
            int(price_drops),
            filename=file.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result.pop("provider", None)
    return result


@app.get("/api/b2c/{dataset_id}")
def b2c_dataset(dataset_id: str, request: Request, response: Response) -> dict[str, Any]:
    spec = marketplace.get_dataset(dataset_id) or PROVIDERS_REGISTRY.get(dataset_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    body = _paid_body(dataset_id, response)
    tx = _header(request, "x402-Tx-Hash") or _header(request, "PAYMENT-SIGNATURE")
    if str(dataset_id).startswith("b2c_"):
        marketplace.credit_royalty(
            dataset_id,
            drops=int(spec.get("price_drops") or 0),
            tx_hash=tx,
        )
    return body
