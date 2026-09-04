from __future__ import annotations

from fastapi import FastAPI

from ledger402.providers import load_json

app = FastAPI(title="Ledger402 free provider")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "free_provider"}


@app.get("/intelligence/port-congestion")
def port_congestion() -> dict:
    data = load_json("free_port_data.json")
    data["synthetic"] = True
    return data
